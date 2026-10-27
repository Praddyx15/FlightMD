"""
EKFAnalyser: innovation rejections, solution validity, GPS glitch / bad
accel flags, innovation test ratios and wind-estimate jumps.

Bit maps follow PX4 ekf2 (estimator_status.msg, common.h), v1.12-v1.15:

innovation_check_flags (innovation_fault_status, set = rejected)
  0 hor_vel  1 ver_vel  2 hor_pos  3 ver_pos  4-6 mag x/y/z  7 yaw
  8 airspeed  9 sideslip  10 hagl  11-12 optflow x/y

solution_status_flags (ekf_solution_status, = MAVLink ESTIMATOR_STATUS_FLAGS)
  0 attitude  1 vel_horiz  2 vel_vert  3 pos_horiz_rel  4 pos_horiz_abs
  5 pos_vert_abs  6 pos_vert_agl  7 const_pos_mode  8-9 pred_pos_horiz
  10 gps_glitch  11 accel_error          (0-6 set = good, 10-11 set = bad)

Only armed time counts: before init every flag is 0, which used to read as
"solution invalid" on every log.
"""

import re

import numpy as np

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import (
    confidence, downsample, find_col, find_runs, run_seconds, when,
)
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# bit -> (label, sensor group)
INNOV_FLAGS = {
    0:  ("Horizontal Velocity", "gps"),
    1:  ("Vertical Velocity", "gps"),
    2:  ("Horizontal Position", "gps"),
    3:  ("Vertical Position", "height"),
    4:  ("Magnetometer X", "mag"),
    5:  ("Magnetometer Y", "mag"),
    6:  ("Magnetometer Z", "mag"),
    7:  ("Yaw", "mag"),
    8:  ("Airspeed", "airspeed"),
    9:  ("Synthetic Sideslip", "airspeed"),
    10: ("Height Above Ground", "range"),
    11: ("Optical Flow X", "flow"),
    12: ("Optical Flow Y", "flow"),
}

SENSOR_ADVICE = {
    "gps": "Check the GPS: antenna placement, interference from other electronics, and EKF2_GPS_DELAY.",
    "height": "Check the height source: barometer foam/covering against prop wash, and the EKF2 height reference setting.",
    "mag": "Recalibrate the compass away from metal and check for interference from power wires or the battery.",
    "airspeed": "Check the pitot tube for blockage and recalibrate the airspeed sensor.",
    "range": "Check the range finder mounting, orientation and that it isn't seeing the landing gear.",
    "flow": "Check the optical flow lens, mounting orientation and that there is enough light and ground texture.",
}

# bit -> label; bits that must be valid whenever the EKF is running
SOLUTION_ALWAYS = {0: "Attitude", 5: "Vertical Position (Absolute)"}
# only expected once the aiding source exists, so judged after first valid
SOLUTION_ONCE_VALID = {
    1: "Horizontal Velocity",
    2: "Vertical Velocity",
    3: "Horizontal Position (Relative)",
    4: "Horizontal Position (Absolute)",
}
GPS_GLITCH_BIT = 10
ACCEL_ERROR_BIT = 11

# estimator_innovation_test_ratios columns that are ratios; anything else
# (timestamp, timestamp_sample, unknown fields) is ignored
RATIO_COL = re.compile(
    r"^(gps|ev|rng|baro|aux|flow|heading|mag|gravity|drag|airspeed|beta|hagl)[a-z0-9_]*(\[\d+\])?$"
    r"|^[a-z]+_test_ratio$"
)
RATIO_LABELS = {
    "gps_hvel": "GPS Horizontal Velocity", "gps_vvel": "GPS Vertical Velocity",
    "gps_hpos": "GPS Horizontal Position", "gps_vpos": "GPS Vertical Position",
    "ev_hvel": "Vision Horizontal Velocity", "ev_vvel": "Vision Vertical Velocity",
    "ev_hpos": "Vision Horizontal Position", "ev_vpos": "Vision Vertical Position",
    "rng_vpos": "Range Finder Height", "baro_vpos": "Barometer Height",
    "aux_hvel": "Auxiliary Velocity", "aux_vvel": "Auxiliary Vertical Velocity",
    "flow": "Optical Flow", "heading": "Heading", "mag_field": "Magnetometer",
    "gravity": "Gravity (Accelerometer)", "drag": "Drag", "airspeed": "Airspeed",
    "beta": "Sideslip", "hagl": "Height Above Ground", "hagl_rate": "Height Above Ground Rate",
    "vel_test_ratio": "Velocity", "pos_test_ratio": "Position", "hgt_test_ratio": "Height",
    "mag_test_ratio": "Magnetometer", "tas_test_ratio": "Airspeed",
    "hagl_test_ratio": "Height Above Ground", "beta_test_ratio": "Sideslip",
}

# todo: ArduPilot XKF4 test ratios, once the .bin parser maps them to these names
SUSTAINED_FAILURE_S = 0.5
INVALID_MIN_FRACTION = 0.01
WIND_CHANGE_THRESH = 5.0       # m/s in one step


class EKFAnalyser(BaseAnalyser):
    name            = "ekf"
    display_name    = "EKF Health Analysis"
    required_topics = ["estimator_status"]
    optional_topics = ["estimator_innovation_test_ratios", "vehicle_status"]

    def analyse(self, topics, params):
        df = topics["estimator_status"]
        if "timestamp" not in df.columns:
            return self._skip("estimator_status has no timestamps.")
        df = df.sort_values("timestamp").reset_index(drop=True)
        phases = flight_phases(topics)

        keep = phases.mask(df["timestamp"].to_numpy(float), "armed")
        if not phases.known and "solution_status_flags" in df.columns:
            # no arming data: start once the EKF has an attitude solution
            sol_all = df["solution_status_flags"].to_numpy(float)
            attitude_ok = (np.nan_to_num(sol_all).astype(int) & 1) == 1
            ok = np.flatnonzero(np.isfinite(sol_all) & attitude_ok)
            if len(ok):
                keep[: ok[0]] = False
        est = df[keep].reset_index(drop=True)
        ts = est["timestamp"].to_numpy(float)

        ratio_df = topics.get("estimator_innovation_test_ratios")
        if ratio_df is not None and "timestamp" in ratio_df.columns:
            ratio_df = ratio_df.sort_values("timestamp")
            ratio_df = ratio_df[phases.mask(ratio_df["timestamp"].to_numpy(float), "armed")]
        else:
            ratio_df = None

        if len(est) < 2 and (ratio_df is None or len(ratio_df) < 2):
            return self._skip(f"No EKF status samples {phases.describe('armed')}.")

        findings: list[Finding] = []
        health_score = 100.0

        # a missing flags sample is no data, not "every bit clear"
        if "innovation_check_flags" in est.columns and est["innovation_check_flags"].notna().sum() > 1:
            have = est["innovation_check_flags"].notna().to_numpy()
            flags = est["innovation_check_flags"][have].astype(int).to_numpy()
            f, p = self._innov_flags(flags, ts[have])
            findings += f
            health_score -= min(p, 60.0)

        if "solution_status_flags" in est.columns and est["solution_status_flags"].notna().sum() > 1:
            have = est["solution_status_flags"].notna().to_numpy()
            sol = est["solution_status_flags"][have].astype(int).to_numpy()
            f, p = self._solution_flags(sol, ts[have])
            findings += f
            health_score -= min(p, 45.0)

        groups = {}
        if ratio_df is not None and len(ratio_df) > 1:
            groups = self._ratio_groups(ratio_df)
            f, p = self._innov_ratios(groups, ratio_df["timestamp"].to_numpy(float))
            findings += f
            health_score -= min(p, 30.0)

        wn = find_col(est, ["wind_vel_n", "wind[0]"])
        we = find_col(est, ["wind_vel_e", "wind[1]"])
        if wn and we and len(est) > 1:
            f, p = self._wind(est[wn].to_numpy(float), est[we].to_numpy(float), ts)
            findings += f
            health_score -= p

        if ratio_df is not None and len(ratio_df) > 1:
            chart_ts = ratio_df["timestamp"].to_numpy(float)
            names = list(groups)
            chart_ts_ms, *vals = downsample(chart_ts, *(groups[n] for n in names))
            chart_data = {"timestamps": chart_ts_ms, "innov_ratios": dict(zip(names, vals))}
        else:
            chart_data = {"timestamps": downsample(ts)[0], "innov_ratios": {}}
        for f in findings:
            if f.chart_data is None:
                f.chart_data = chart_data

        key_metrics = {}
        peaks = [np.nanmax(v) for v in groups.values() if np.isfinite(v).any()]
        if peaks:
            key_metrics["max_innovation_ratio"] = round(float(max(peaks)), 4)

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics=key_metrics,
        )

    def _innov_flags(self, flags, ts):
        findings, penalty = [], 0.0
        for bit, (label, group) in INNOV_FLAGS.items():
            on = (flags & (1 << bit)) != 0
            if not on.any():
                continue
            runs = find_runs(on)
            durs = [run_seconds(ts, a, b) for a, b in runs]
            longest = max(durs)
            sustained = longest >= SUSTAINED_FAILURE_S
            penalty += 15.0 if sustained else 5.0
            tech = (
                f"EKF rejected {label.lower()} measurements in {int(on.sum())} samples while armed; "
                f"longest run {longest:.2f}s (innovation_check_flags bit {bit})."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING if sustained else Severity.INFO,
                kind="ekf.innovation_rejected",
                title=f"EKF Innovation Failure: {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation=SENSOR_ADVICE[group],
                confidence=confidence(longest / SUSTAINED_FAILURE_S - 1, longest),
                **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
            ))
        return findings, penalty

    def _solution_flags(self, sol, ts):
        findings, penalty = [], 0.0
        n = len(sol)

        for bit, label in {**SOLUTION_ALWAYS, **SOLUTION_ONCE_VALID}.items():
            good = (sol & (1 << bit)) != 0
            if bit in SOLUTION_ONCE_VALID:
                first = np.flatnonzero(good)
                if not len(first):
                    continue    # that aiding source never came up (e.g. no GPS)
                good = good[first[0]:]
                t = ts[first[0]:]
            else:
                t = ts
            bad = ~good
            frac = bad.mean() if len(bad) else 0.0
            if frac < INVALID_MIN_FRACTION:
                continue
            penalty += 15.0
            runs = find_runs(bad)
            longest = max(run_seconds(t, a, b) for a, b in runs)
            tech = (
                f"EKF {label.lower()} estimate invalid for {frac * 100:.1f}% of armed time "
                f"({int(bad.sum())} samples, longest {longest:.1f}s; solution_status_flags bit {bit})."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING,
                kind="ekf.solution_invalid",
                title=f"EKF Solution Invalid: {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Check sensor health and calibration before the next flight, and avoid modes that need this estimate until it's resolved.",
                confidence=confidence(frac / 0.1 - 1, longest),
                **when(t[runs[0][0]], t[min(runs[-1][1], len(t) - 1)]),
            ))

        for bit, kind, title, sev, rec in (
            (GPS_GLITCH_BIT, "ekf.gps_glitch", "EKF Detected a GPS Glitch", Severity.WARNING,
             "The EKF saw GPS jump away from its own estimate. Check for multipath near structures and GPS interference; review the flight path at that time."),
            (ACCEL_ERROR_BIT, "ekf.accel_error", "EKF Detected Bad Accelerometer Data", Severity.CRITICAL,
             "Bad accelerometer data usually means clipping from heavy vibration. Check props, motor mounts and flight-controller damping before flying again."),
        ):
            on = (sol & (1 << bit)) != 0
            if not on.any():
                continue
            runs = find_runs(on)
            longest = max(run_seconds(ts, a, b) for a, b in runs)
            penalty += 30.0 if sev == Severity.CRITICAL else 15.0
            tech = (
                f"solution_status_flags bit {bit} set in {int(on.sum())} of {n} armed samples "
                f"({len(runs)} episode(s), longest {longest:.1f}s)."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=sev,
                kind=kind,
                title=title,
                technical_summary=tech,
                plain_english=tech,
                recommendation=rec,
                confidence=confidence(len(runs) / 3.0, longest),
                **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
            ))
        return findings, penalty

    def _ratio_groups(self, ratio_df) -> dict[str, np.ndarray]:
        """Ratio columns grouped by field (gps_hpos[0] and [1] -> gps_hpos,
        worst of the two)."""
        groups: dict[str, np.ndarray] = {}
        for col in ratio_df.columns:
            if col.startswith("timestamp") or not RATIO_COL.match(col):
                continue
            base = col.split("[")[0]
            v = ratio_df[col].to_numpy(float)
            groups[base] = v if base not in groups else np.fmax(groups[base], v)
        return groups

    def _innov_ratios(self, groups, ts):
        findings, penalty = [], 0.0
        for base, v in groups.items():
            failed = v > 1.0
            if not failed.any():
                continue
            runs = find_runs(failed)
            durs = [run_seconds(ts, a, b) for a, b in runs]
            longest = max(durs)
            sustained = longest >= SUSTAINED_FAILURE_S
            penalty += 15.0 if sustained else 5.0
            label = RATIO_LABELS.get(base, base.replace("_", " ").title()[:40])
            tech = (
                f"{label} innovation test ratio went over 1.0 (measurement rejected) in "
                f"{int(failed.sum())} samples while armed; peak {np.nanmax(v):.2f}, "
                f"longest {longest:.2f}s."
            )
            a, b = runs[int(np.argmax(durs))]
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING if sustained else Severity.INFO,
                kind="ekf.innovation_ratio",
                title=f"EKF Innovation Ratio Exceeded: {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Find which sensor this ratio belongs to and check its calibration and mounting; a ratio stuck over 1 means the EKF is ignoring that sensor.",
                confidence=confidence(float(np.nanmax(v)) - 1, longest),
                chart_data=dict(zip(["timestamps", "ratio"], downsample(ts, v)), col=base),
                **when(ts[a], ts[min(b, len(ts) - 1)]),
            ))
        return findings, penalty

    def _wind(self, wn, we, ts):
        speed = np.hypot(wn, we)
        delta = np.abs(np.diff(speed))
        jumps = np.flatnonzero(delta > WIND_CHANGE_THRESH)
        if not len(jumps):
            return [], 0.0
        biggest = float(np.nanmax(delta))
        tech = (
            f"EKF wind estimate changed by more than {WIND_CHANGE_THRESH} m/s in a single step "
            f"{len(jumps)} time(s) while armed; biggest jump {biggest:.1f} m/s."
        )
        return [Finding(
            category=Category.EKF,
            severity=Severity.WARNING,
            kind="ekf.wind_jump",
            title="Unexpected Wind Estimation Jump",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Sudden wind jumps usually follow a GPS glitch or an airspeed sensor dropout. Review GPS and pitot data around that time.",
            confidence=confidence(biggest / WIND_CHANGE_THRESH - 1),
            **when(ts[jumps[0]], ts[jumps[-1] + 1]),
        )], 10.0
