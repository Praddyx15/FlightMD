"""
MotorAnalyser: per-motor balance at hover, ESC temperature, current
imbalance and RPM dropouts, from ESC telemetry (BLHeli32/AM32/KISS/DShot).
Most logs have none and the module is skipped.

Only real ESCs count: PX4 always logs 8 esc[] slots, so columns beyond
esc_count, or that never report anything, are dropped. Missing samples stay
NaN; NaN is "no data", never "motor stopped".
"""

import re

import numpy as np

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, downsample, find_runs, run_seconds, when
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# spread of per-motor hover RPM: std / mean
BALANCE_WARNING  = 0.08
BALANCE_CRITICAL = 0.15

TEMP_WARNING_C = 80.0

# one motor's hover current this far above the mean
CURRENT_IMBALANCE_PCT = 0.20

SPINNING_RPM = 500.0
STOPPED_RPM = 100.0
OTHERS_FLYING_RPM = 1000.0
RPM_DROPOUT_MS = 100.0

HOVER_BAND = 0.15      # within ±15% of the in-flight median mean-RPM
MIN_HOVER_SAMPLES = 50

_ESC_COL = re.compile(r"^esc\[(\d+)\]\.esc_(\w+)$")


class MotorAnalyser(BaseAnalyser):
    name            = "motors"
    display_name    = "Motor / ESC Analysis"
    required_topics = ["esc_status"]

    def analyse(self, topics, params):
        df = topics["esc_status"]
        if "timestamp" not in df.columns:
            return self._skip("esc_status has no timestamps.")
        df = df.sort_values("timestamp").reset_index(drop=True)

        esc_count = None
        if "esc_count" in df.columns and df["esc_count"].notna().any():
            esc_count = int(df["esc_count"].max())

        rpm_cols = self._motor_cols(df, "rpm", esc_count)
        if not rpm_cols:
            return self._skip("No ESC RPM telemetry in this log.")
        temp_cols = self._motor_cols(df, "temperature", esc_count)
        curr_cols = self._motor_cols(df, "current", esc_count)

        ts = df["timestamp"].to_numpy(float)
        rpm = df[[c for _, c in rpm_cols]].to_numpy(float)
        phases = flight_phases(topics)
        in_air = phases.mask(ts, "in_air")
        if not phases.known:
            # no arming data: "flying" = most motors clearly spinning
            in_air &= (np.nan_to_num(rpm) > SPINNING_RPM).mean(axis=1) > 0.5

        findings: list[Finding] = []
        health_score = 100.0
        key_metrics: dict[str, float] = {}

        hover = self._hover_mask(rpm, in_air)
        if hover.sum() > MIN_HOVER_SAMPLES and len(rpm_cols) >= 2:
            f, p = self._balance(df, rpm, hover, ts, rpm_cols, curr_cols, key_metrics)
            findings += f
            health_score -= p

        for i, col in temp_cols:
            temp = df[col].to_numpy(float)
            if not np.isfinite(temp).any():
                continue
            peak = float(np.nanmax(temp))
            if peak <= TEMP_WARNING_C:
                continue
            health_score -= 15
            hot = np.flatnonzero(temp > TEMP_WARNING_C)
            tech = f"ESC {i + 1} temperature reached {peak:.0f}°C (threshold {TEMP_WARNING_C:.0f}°C)."
            findings.append(Finding(
                category=Category.MOTORS,
                severity=Severity.WARNING,
                kind="motors.esc_thermal",
                title=f"ESC Thermal Stress — Motor {i + 1} ({peak:.0f}°C)",
                technical_summary=tech,
                plain_english=tech,
                recommendation=f"Reduce sustained full-throttle time. Ensure ESC {i + 1} has adequate airflow. Check for prop size mismatch.",
                confidence=confidence((peak - TEMP_WARNING_C) / 20.0),
                **when(ts[hot[0]], ts[hot[-1]]),
            ))

        f, p = self._dropouts(rpm, in_air, ts, rpm_cols)
        findings += f
        health_score -= p

        ts_ms, *series = downsample(ts, *(rpm[:, k] for k in range(rpm.shape[1])))
        chart = {"timestamps": ts_ms, "rpm_per_motor": {c: s for (_, c), s in zip(rpm_cols, series)}}
        for f in findings:
            f.chart_data = {**chart, **(f.chart_data or {})}

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics=key_metrics,
        )

    def _motor_cols(self, df, field, esc_count) -> list[tuple[int, str]]:
        """[(motor index, column)] for real ESCs, ordered by index."""
        found = []
        for col in df.columns:
            m = _ESC_COL.match(col)
            if m and field in m.group(2):
                found.append((int(m.group(1)), col))
        if not found:
            # older parsers: esc_rpm[0], motor_1_rpm ...
            loose = sorted(c for c in df.columns
                           if field in c.lower() and ("esc" in c.lower() or "motor" in c.lower()))
            found = list(enumerate(loose))
        found.sort()
        if esc_count:
            found = [(i, c) for i, c in found if i < esc_count]
        # slots that never reported, or only ever report 0, aren't motors
        return [(i, c) for i, c in found
                if df[c].notna().any() and (df[c].fillna(0) != 0).any()]

    def _hover_mask(self, rpm, in_air):
        valid = np.isfinite(rpm).all(axis=1) & (np.nan_to_num(rpm) > SPINNING_RPM).all(axis=1) & in_air
        if not valid.any():
            return valid
        mean = rpm.mean(axis=1)
        typical = np.median(mean[valid])
        return valid & (np.abs(mean - typical) <= HOVER_BAND * typical)

    def _balance(self, df, rpm, hover, ts, rpm_cols, curr_cols, key_metrics):
        findings, penalty = [], 0.0
        per_motor = np.median(rpm[hover], axis=0)
        mean = float(per_motor.mean())
        dev = (per_motor - mean) / mean
        idx = float(per_motor.std() / mean)
        key_metrics["motor_balance_index"] = round(idx, 4)
        for (i, _), d in zip(rpm_cols, dev):
            key_metrics[f"motor_{i + 1}_rpm_dev_pct"] = round(float(d * 100), 2)

        motors = [{"motor": i + 1, "hover_rpm": round(float(r), 1), "deviation_pct": round(float(d * 100), 2)}
                  for (i, _), r, d in zip(rpm_cols, per_motor, dev)]

        currents = None
        if len(curr_cols) >= 2:
            cur = df[[c for _, c in curr_cols]].to_numpy(float)[hover]
            if np.isfinite(cur).any(axis=0).all():
                currents = np.nanmedian(cur, axis=0)
                by_motor = dict(zip((i for i, _ in curr_cols), currents))
                for m in motors:
                    c = by_motor.get(m["motor"] - 1)
                    m["hover_current_a"] = None if c is None else round(float(c), 2)

        hover_runs = find_runs(hover)
        a, b = max(hover_runs, key=lambda r: r[1] - r[0])
        span = when(ts[a], ts[min(b, len(ts) - 1)])

        worst = int(np.argmax(np.abs(dev)))
        worst_motor = rpm_cols[worst][0] + 1
        worst_dev = float(dev[worst] * 100)
        sev = None
        if idx > BALANCE_CRITICAL:
            sev, p, thr = Severity.CRITICAL, 30.0, BALANCE_CRITICAL
        elif idx > BALANCE_WARNING:
            sev, p, thr = Severity.WARNING, 15.0, BALANCE_WARNING
        if sev is not None:
            penalty += p
            lines = ", ".join(f"M{m['motor']} {m['deviation_pct']:+.1f}%" for m in motors)
            tech = (
                f"Hover RPM spread (std/mean) {idx:.3f}, threshold {thr}. Mean hover RPM {mean:.0f}. "
                f"Per motor vs mean: {lines}."
            )
            findings.append(Finding(
                category=Category.MOTORS,
                severity=sev,
                kind="motors.rpm_imbalance",
                title=f"Motor Imbalance — Motor {worst_motor} at {worst_dev:+.0f}%",
                technical_summary=tech,
                plain_english=tech,
                recommendation=(
                    f"Motor {worst_motor} is furthest from the others. Check its prop (damage, seating, "
                    f"right type), its bearings by hand, and the frame arm for twist; then check the "
                    f"centre of gravity, which also shifts load between motors."
                ),
                confidence=confidence(idx / thr - 1, hover.sum() / 50.0),
                chart_data={"per_motor": motors},
                **span,
            ))

        if currents is not None:
            cmean = float(np.mean(currents))
            if cmean > 0:
                cdev = (currents - cmean) / cmean
                j = int(np.argmax(cdev))
                if cdev[j] > CURRENT_IMBALANCE_PCT:
                    penalty += 15.0
                    motor = curr_cols[j][0] + 1
                    tech = (
                        f"At hover, motor {motor} drew {currents[j]:.1f} A against a mean of "
                        f"{cmean:.1f} A ({cdev[j] * 100:.0f}% more; threshold {CURRENT_IMBALANCE_PCT * 100:.0f}%)."
                    )
                    findings.append(Finding(
                        category=Category.MOTORS,
                        severity=Severity.WARNING,
                        kind="motors.current_imbalance",
                        title=f"Motor Current Imbalance — Motor {motor}",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation=f"Inspect motor {motor} for mechanical drag, binding, or stator damage. Check propeller for cracks.",
                        confidence=confidence(cdev[j] / CURRENT_IMBALANCE_PCT - 1, hover.sum() / 50.0),
                        chart_data={"per_motor": motors},
                        **span,
                    ))
        return findings, penalty

    def _dropouts(self, rpm, in_air, ts, rpm_cols):
        findings, penalty = [], 0.0
        n = rpm.shape[1]
        for k, (i, col) in enumerate(rpm_cols):
            mine = rpm[:, k]
            if n > 1:
                # missing samples count as 0 here, i.e. "not clearly flying"
                others = np.median(np.nan_to_num(np.delete(rpm, k, axis=1)), axis=1)
            else:
                others = np.full(len(mine), np.inf)
            # this motor stopped while the rest kept flying; a spin-down
            # after landing takes every motor down together
            stopped = in_air & (mine < STOPPED_RPM) & (others > OTHERS_FLYING_RPM)
            for a, b in find_runs(stopped):
                dur_ms = run_seconds(ts, a, b) * 1e3
                if dur_ms <= RPM_DROPOUT_MS:
                    continue
                penalty += 30.0
                tech = (
                    f"Motor {i + 1} RPM fell below {STOPPED_RPM:.0f} for {dur_ms:.0f}ms at "
                    f"t={ts[a] / 1e6:.1f}s in flight while the other motors stayed above "
                    f"{OTHERS_FLYING_RPM:.0f} RPM."
                )
                findings.append(Finding(
                    category=Category.MOTORS,
                    severity=Severity.CRITICAL,
                    kind="motors.dropout",
                    title=f"Motor {i + 1} Dropout Detected ({dur_ms:.0f}ms)",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=f"Do NOT fly this aircraft until motor {i + 1} is inspected and tested. Check ESC connection, motor windings, and prop nut.",
                    confidence=confidence(dur_ms / RPM_DROPOUT_MS - 1, dur_ms / 1e3),
                    **when(ts[a], ts[min(b, len(ts) - 1)]),
                ))
                break   # one per motor
        return findings, penalty
