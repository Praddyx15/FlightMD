"""
VibrationAnalyser: vibration level, accelerometer clipping and agreement
between IMUs, in flight only.

The autopilot's own numbers come first, so the figures match what Flight
Review and Mission Planner show for the same log:

  PX4        vehicle_imu_status.accel_vibration_metric (m/s²), with Flight
             Review's bands: under 4.9 (0.5 g) fine, over 9.8 (1 g) too high.
             accel_clipping[0..2] and the error counts are running totals.
  ArduPilot  `vibration` (VIBE / MAVLink VIBRATION): vibration_x/y/z in m/s²,
             ArduPilot's limits: under 30 fine, over 60 nearly always a
             problem. clipping_0..2 are running totals, one per IMU.
  PX4 tlog   PX4 fills VIBRATION its own way: vibration_z is the accel
             metric above (x and y are gyro metrics), so it gets PX4's bands.

Only without any of those is a level computed from raw sensor_accel: take
out everything below ~5 Hz (gravity, manoeuvres) and RMS what's left, which
reads on VIBE's scale, so 30 / 60 apply there too.

The level is the 95th percentile over the flight, so a few spikes (a hard
landing, a gust) don't make a finding and a sustained level does. Raw
accel gets the whole-flight RMS instead; it's an average already.
"""

import re

import numpy as np
import pandas as pd

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, downsample, find_col, sample_rate_hz, when
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.analysers.vehicle import vehicle_from_params
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# (warning, critical) per metric, m/s²
ARDU_LIMITS = (30.0, 60.0)          # ArduPilot "Measuring Vibration" page
PX4_LIMITS = (4.905, 9.81)          # Flight Review's vibration-metric bands
RMS_WARNING, RMS_CRITICAL = ARDU_LIMITS

LEVEL_PERCENTILE = 95
MIN_METRIC_SAMPLES = 10
MIN_RAW_SAMPLES = 50

HPF_CUTOFF_S = 0.2      # rolling-mean length ≈ 5 Hz high-pass
RMS_WINDOW_S = 1.0      # windowed RMS, for when it happened

# ArduPilot: clip counts should be zero, "low numbers (<100) are likely ok
# especially if they occur during hard landings"
CLIP_COUNTER_WARNING = 100

# plateau fallback: only plausible as range clipping above ~7.5 g
CLIP_MIN_RANGE = 75.0
CLIP_PLATEAU = 0.99
CLIP_MIN_FRACTION = 0.001   # of in-flight samples
CLIP_MIN_COUNT = 10

IMU_ERROR_MIN = 10          # driver errors in flight before we mention them
MISMATCH_FRACTION = 0.5     # IMUs disagreeing by half the warning level
IMU_CONSISTENCY_THRESH = MISMATCH_FRACTION * RMS_WARNING

_RAW = re.compile(r"^sensor_accel(?:_(\d+))?$")
_IMU_STATUS = re.compile(r"^vehicle_imu_status(?:_(\d+))?$")
_VIBE = re.compile(r"^vibration(?:_(\d+))?$")
_CLIP_K = re.compile(r"^clipping_(\d)$")


def _instances(topics, pattern):
    """[(index, topic, df)]: the bare name is instance 0, _1/_2 the others.
    An old-style name_0 next to the bare name is the same data."""
    found = {}
    for key, df in topics.items():
        m = pattern.match(key)
        if not m or df is None or "timestamp" not in df.columns:
            continue
        idx = int(m.group(1) or 0)
        if idx in found and m.group(1) is not None:
            continue
        found[idx] = (idx, key, df)
    return [found[i] for i in sorted(found)]


def counter_increase(v, inflight) -> int:
    """How much a running total went up between in-flight samples."""
    v = np.asarray(v, dtype=float)
    ok = np.isfinite(v)
    v, inflight = v[ok], np.asarray(inflight)[ok]
    if len(v) < 2:
        return 0
    d = np.diff(v)
    d[d < 0] = 0        # a drop is the counter restarting, not negative clips
    return int(d[inflight[1:] & inflight[:-1]].sum())


class VibrationAnalyser(BaseAnalyser):
    name          = "vibration"
    display_name  = "Vibration Analysis"
    weight        = 20.0
    required_any  = ["vehicle_imu_status", "vibration", "sensor_accel"]
    optional_topics = ["vehicle_status", "vehicle_land_detected"]

    def analyse(self, topics, params):
        phases = flight_phases(topics)
        px4 = vehicle_from_params(params).autopilot == "px4"

        imus = self._imu_status(topics, phases) or self._vibe(topics, phases, px4) or self._raw(topics, phases)
        if not imus:
            return self._skip(f"Not enough vibration or accelerometer data {phases.describe()}.")
        clips = self._clip_counts(topics, phases)

        findings: list[Finding] = []
        health_score = 100.0
        chart_data = {"instances": {i["topic"]: i["chart"] for i in imus}}

        for imu in imus:
            f = self._level_finding(imu, phases)
            if f is not None:
                health_score -= 30 if f.severity == Severity.CRITICAL else 15
                findings.append(f)

            if imu.get("errors", 0) >= IMU_ERROR_MIN:
                health_score -= 5
                tech = (f"{imu['label']}: the sensor driver reported {imu['errors']} accelerometer/gyro "
                        f"errors in flight (vehicle_imu_status error counts).")
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.INFO,
                    kind="vibration.imu_errors",
                    title=f"IMU Sensor Errors — {imu['label']}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Occasional errors are harmless; a steady rise points at a failing sensor, a loose board connector or electrical noise on the bus.",
                    confidence=confidence(imu["errors"] / IMU_ERROR_MIN - 1),
                    chart_data={"instance": imu["topic"], **imu["chart"]},
                ))

        for idx, (n, source, is_counter, n_samples) in sorted(clips.items()):
            label = f"IMU {idx}"
            if is_counter:
                if n <= 0:
                    continue
                sev = Severity.WARNING if n >= CLIP_COUNTER_WARNING else Severity.INFO
                thr = CLIP_COUNTER_WARNING
            else:
                if n < CLIP_MIN_COUNT or n < CLIP_MIN_FRACTION * n_samples:
                    continue
                sev = Severity.WARNING
                thr = max(CLIP_MIN_COUNT, CLIP_MIN_FRACTION * n_samples)
            health_score -= 15 if sev == Severity.WARNING else 5
            tech = (
                f"{label}: {n} accelerometer clipping events in flight ({source}). "
                f"The sensor hit its range limit, which corrupts the attitude and height estimate."
            )
            findings.append(Finding(
                category=Category.VIBRATION,
                severity=sev,
                kind="vibration.clipping",
                title=f"{'Hard ' if sev == Severity.WARNING else ''}IMU Clipping Detected — {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Look for a loose prop, a damaged motor bell or a hard impact. Check all prop nuts are tight and that the flight controller sits on its damping mount.",
                confidence=confidence(n / thr - 1),
                chart_data=chart_data,
            ))

        levels = {i["label"]: i["level"] for i in imus}
        warn = imus[0]["limits"][0]
        if len(levels) >= 2:
            spread = max(levels.values()) - min(levels.values())
            limit = MISMATCH_FRACTION * warn
            if spread > limit:
                health_score -= 15
                per = ", ".join(f"{k} {v:.1f}" for k, v in levels.items())
                tech = (
                    f"IMU instances disagree by {spread:.1f} m/s² ({imus[0]['metric']}, "
                    f"threshold {limit:.1f}). Per IMU: {per}."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.WARNING,
                    kind="vibration.imu_mismatch",
                    title="IMU Instance Inconsistency",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Check flight controller mounting. One IMU may be poorly isolated from vibration path.",
                    confidence=confidence(spread / limit - 1),
                    chart_data=chart_data,
                ))

        worst = max(imus, key=lambda i: i["level"] / i["limits"][0])
        key_metrics = {
            "vibration_vs_limit": round(worst["level"] / worst["limits"][0], 3),
            "total_clip_count": float(sum(c[0] for c in clips.values())),
        }
        if worst["source"] == "px4_metric":
            key_metrics["max_accel_vibration_metric"] = round(max(levels.values()), 3)
            gyro = [i["gyro"] for i in imus if i.get("gyro") is not None]
            if gyro:
                key_metrics["max_gyro_vibration_metric"] = round(max(gyro), 4)
        else:
            # same scale as VIBE, so trends stay comparable with older reports
            key_metrics["max_imu_rms"] = round(max(levels.values()), 3)

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics=key_metrics,
        )

    def _level_finding(self, imu, phases):
        warn, crit = imu["limits"]
        level = imu["level"]
        if level <= warn:
            return None
        critical = level > crit
        thr = crit if critical else warn
        ts, series = imu["ts"], imu["series"]
        over = np.flatnonzero(series > warn)
        dt = float(np.median(np.diff(ts))) / 1e6 if len(ts) > 1 else 0.0
        tech = (
            f"{imu['label']}: vibration {level:.1f} m/s² {phases.describe()} "
            f"({imu['metric']}{imu.get('stat', f', {LEVEL_PERCENTILE}th percentile')}; "
            f"{'CRITICAL' if critical else 'WARNING'}, threshold {thr:g}). "
            f"Peak {float(np.nanmax(series)):.1f}{imu['detail']}."
        )
        return Finding(
            category=Category.VIBRATION,
            severity=Severity.CRITICAL if critical else Severity.WARNING,
            kind="vibration.critical" if critical else "vibration.elevated",
            title=f"{'Critical' if critical else 'Elevated'} Vibration — {imu['label']}",
            technical_summary=tech,
            plain_english=tech,
            recommendation=(
                "Immediately inspect propellers for balance/damage. Check all motor bell screws and frame arm bolts."
                if critical else
                "Balance propellers using a prop balancer. Inspect motor mounts for looseness."
            ),
            confidence=confidence(level / thr - 1, len(over) * dt),
            chart_data={"instance": imu["topic"], **imu["chart"]},
            **(when(ts[over[0]], ts[over[-1]]) if len(over) else {}),
        )

    def _in_flight(self, df, cols, phases):
        d = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        d = d.dropna(subset=cols, how="all")
        return d[phases.mask(d["timestamp"].to_numpy(float), "in_air")]

    def _imu_status(self, topics, phases):
        out = []
        for idx, topic, df in _instances(topics, _IMU_STATUS):
            if "accel_vibration_metric" not in df.columns:
                continue
            d = self._in_flight(df, ["accel_vibration_metric"], phases)
            v = d["accel_vibration_metric"].to_numpy(float)
            ok = np.isfinite(v)
            if ok.sum() < MIN_METRIC_SAMPLES:
                continue
            ts, v = d["timestamp"].to_numpy(float)[ok], v[ok]
            gyro = None
            if "gyro_vibration_metric" in d.columns and d["gyro_vibration_metric"].notna().any():
                gyro = float(np.nanpercentile(d["gyro_vibration_metric"].to_numpy(float), LEVEL_PERCENTILE))
            errors = 0
            whole = df.dropna(subset=["timestamp"]).sort_values("timestamp")
            flying = phases.mask(whole["timestamp"].to_numpy(float), "in_air")
            for c in ("accel_error_count", "gyro_error_count"):
                if c in whole.columns:
                    errors += counter_increase(whole[c].to_numpy(float), flying)
            t_ms, vs = downsample(ts, v)
            out.append({
                "topic": topic, "label": f"IMU {idx}", "source": "px4_metric",
                "metric": "PX4 accel_vibration_metric", "limits": PX4_LIMITS,
                "ts": ts, "series": v, "level": float(np.percentile(v, LEVEL_PERCENTILE)),
                "detail": "", "gyro": gyro, "errors": errors,
                "chart": {"timestamps": t_ms, "vibe": vs, "metric": "accel_vibration_metric",
                          "warn": PX4_LIMITS[0], "crit": PX4_LIMITS[1]},
            })
        return out

    def _vibe(self, topics, phases, px4):
        out = []
        for idx, topic, df in _instances(topics, _VIBE):
            axes = [c for c in ("vibration_x", "vibration_y", "vibration_z") if c in df.columns]
            if px4:
                # PX4's VIBRATION: z is the accel metric, x/y are gyro metrics
                axes = [c for c in axes if c == "vibration_z"]
            if not axes:
                continue
            d = self._in_flight(df, axes, phases)
            a = d[axes].to_numpy(float)
            ok = np.isfinite(a).any(axis=1)
            if ok.sum() < MIN_METRIC_SAMPLES:
                continue
            ts, a = d["timestamp"].to_numpy(float)[ok], a[ok]
            worst = np.nanmax(a, axis=1)
            p = np.nanpercentile(a, LEVEL_PERCENTILE, axis=0)
            if px4:
                limits, metric, detail = PX4_LIMITS, "PX4 accel vibration metric via MAVLink", ""
                t_ms, vs = downsample(ts, worst)
                chart = {"timestamps": t_ms, "vibe": vs, "metric": "accel_vibration_metric"}
            else:
                limits, metric = ARDU_LIMITS, "autopilot VIBE"
                detail = "; per axis " + ", ".join(f"{c[-1].upper()}={v:.1f}" for c, v in zip(axes, p))
                cols = [d[c].to_numpy(float)[ok] if c in axes else np.full(len(ts), np.nan)
                        for c in ("vibration_x", "vibration_y", "vibration_z")]
                t_ms, xs, ys, zs, vs = downsample(ts, *cols, worst)
                chart = {"timestamps": t_ms, "x": xs, "y": ys, "z": zs, "vibe": vs}
            out.append({
                "topic": topic, "label": f"IMU {idx}", "source": "px4_metric" if px4 else "vibe",
                "metric": metric, "limits": limits, "ts": ts, "series": worst,
                "level": float(np.percentile(worst, LEVEL_PERCENTILE)), "detail": detail,
                "chart": {**chart, "warn": limits[0], "crit": limits[1]},
            })
        return out

    def _raw(self, topics, phases):
        out = []
        for idx, topic, df in _instances(topics, _RAW):
            x_col = find_col(df, ["x", "xyz[0]"])
            y_col = find_col(df, ["y", "xyz[1]"])
            z_col = find_col(df, ["z", "xyz[2]"])
            if not (x_col and y_col and z_col):
                continue
            d = df.dropna(subset=["timestamp", x_col, y_col, z_col]).sort_values("timestamp")
            d = d[phases.mask(d["timestamp"].to_numpy(float), "in_air")]
            if len(d) < MIN_RAW_SAMPLES:
                continue

            ts = d["timestamp"].to_numpy(float)
            fs = sample_rate_hz(ts, 250.0)
            raw = d[[x_col, y_col, z_col]].to_numpy(float)
            n_hp = max(3, int(round(HPF_CUTOFF_S * fs)))
            hp = raw - pd.DataFrame(raw).rolling(n_hp, center=True, min_periods=1).mean().to_numpy()

            rms_axes = np.sqrt(np.mean(hp ** 2, axis=0))
            rms = float(np.sqrt(np.mean(np.sum(hp ** 2, axis=1))))
            n_win = max(1, int(round(RMS_WINDOW_S * fs)))
            win_rms = np.sqrt(pd.Series(np.sum(hp ** 2, axis=1)).rolling(n_win, center=True, min_periods=1).mean().to_numpy())

            ts_ms, xs, ys, zs, vs = downsample(ts, raw[:, 0], raw[:, 1], raw[:, 2], win_rms)
            out.append({
                "topic": topic, "label": f"IMU {idx}", "source": "raw",
                "metric": "computed from raw accel above 5 Hz", "limits": ARDU_LIMITS,
                "ts": ts, "series": win_rms, "level": rms, "stat": ", whole-flight RMS",
                "detail": (f" in the worst 1 s window; per axis X={rms_axes[0]:.1f}, "
                           f"Y={rms_axes[1]:.1f}, Z={rms_axes[2]:.1f}"),
                "chart": {
                    "timestamps": ts_ms, "x": xs, "y": ys, "z": zs, "vibe": vs,
                    "rms_x": float(rms_axes[0]), "rms_y": float(rms_axes[1]), "rms_z": float(rms_axes[2]),
                    "combined_rms": rms, "warn": ARDU_LIMITS[0], "crit": ARDU_LIMITS[1],
                },
            })
        return out

    def _clip_counts(self, topics, phases) -> dict:
        """IMU index -> (in-flight clip count, source text, from a counter?,
        in-flight sample count). Autopilot counters first."""
        out = {}

        for idx, _, df in _instances(topics, _IMU_STATUS):
            cols = [c for c in df.columns if c.startswith("accel_clipping")]
            if cols:
                d = df.dropna(subset=["timestamp"]).sort_values("timestamp")
                flying = phases.mask(d["timestamp"].to_numpy(float), "in_air")
                n = sum(counter_increase(d[c].to_numpy(float), flying) for c in cols)
                out[idx] = (n, "vehicle_imu_status.accel_clipping", True, int(flying.sum()))

        # clipping_k belongs to IMU k whichever vibration topic carries it
        for _, _, df in _instances(topics, _VIBE):
            d = df.dropna(subset=["timestamp"]).sort_values("timestamp")
            flying = phases.mask(d["timestamp"].to_numpy(float), "in_air")
            for c in d.columns:
                m = _CLIP_K.match(c)
                if not m or int(m.group(1)) in out:
                    continue
                n = counter_increase(d[c].to_numpy(float), flying)
                out[int(m.group(1))] = (n, "autopilot clip counter", True, int(flying.sum()))

        for idx, _, df in _instances(topics, _RAW):
            if idx in out:
                continue
            res = self._raw_clips(df, phases)
            if res is not None:
                out[idx] = res
        return out

    def _raw_clips(self, df, phases):
        d = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        flying = phases.mask(d["timestamp"].to_numpy(float), "in_air")
        counters = [c for c in d.columns if c.startswith("clip_counter")]
        if counters:
            # PX4 sensor_accel.clip_counter[3]: clips per axis in that sample
            n = int(np.nansum(d.loc[flying, counters].to_numpy(float)))
            return n, "sensor_accel clip counter", True, int(flying.sum())

        cols = [find_col(d, [a, f"xyz[{k}]"]) for k, a in enumerate("xyz")]
        if not all(cols):
            return None
        raw = d.loc[flying, cols].dropna().to_numpy(float)
        if len(raw) < MIN_RAW_SAMPLES:
            return None
        total = 0
        for k in range(3):
            a = np.abs(raw[:, k])
            top = float(np.nanmax(a))
            if top < CLIP_MIN_RANGE:
                continue
            n = int(np.sum(a >= CLIP_PLATEAU * top))
            if n >= 3:      # one sample at the max is just the max
                total += n
        return total, "samples flat at the sensor's range limit", False, len(raw)
