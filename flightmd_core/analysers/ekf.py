"""
EKFAnalyser: innovation rejections, solution validity, GPS glitch / bad
accel flags, innovation test ratios, filter faults and timeouts, and
wind-estimate jumps.

Sources, autopilot's own numbers throughout:
  estimator_status                  PX4 .ulg flags (below), wind
  estimator_innovation_test_ratios  PX4 .ulg per-sensor ratios; without it
                                    estimator_status's own *_test_ratio
  ekf_test_ratios                   ArduPilot XKF4/NKF4 (primary core) and
                                    tlogs: *_test_ratio, plus solution_status
                                    (.bin, nav_filter_status bits),
                                    fault_status, timeout_status, or flags
                                    (tlog, MAVLink EKF/ESTIMATOR status bits)

Every ratio is on PX4's scale, innov² / (gate² · innov_var), 1.0 =
measurement rejected; PX4's estimator_status and MAVLink ESTIMATOR_STATUS
carry it as is. ArduPilot logs the square root (SV, SP...), and the parser
squares it, so Mission Planner's 0.8 "warning" is 0.64 here.

Bit maps follow PX4 ekf2 (estimator_status.msg, common.h), v1.12-v1.15:

innovation_check_flags (innovation_fault_status, set = rejected)
  0 hor_vel  1 ver_vel  2 hor_pos  3 ver_pos  4-6 mag x/y/z  7 yaw
  8 airspeed  9 sideslip  10 hagl  11-12 optflow x/y

solution_status_flags (ekf_solution_status, = MAVLink ESTIMATOR_STATUS_FLAGS)
  0 attitude  1 vel_horiz  2 vel_vert  3 pos_horiz_rel  4 pos_horiz_abs
  5 pos_vert_abs  6 pos_vert_agl  7 const_pos_mode  8-9 pred_pos_horiz
  10 gps_glitch  11 accel_error          (0-6 set = good, 10-11 set = bad)

ArduPilot's nav_filter_status (XKF4.SS) agrees on bits 0-9; its GPS glitch is
bit 14. MAVLink EKF_STATUS_REPORT (ArduPilot tlogs) has bit 10 for
"uninitialised" and the glitch on bit 15.

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
from flightmd_core.analysers.vehicle import vehicle_from_params
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
    "gps": "Check the GPS: antenna placement and interference from other electronics.",
    "height": "Check the height source: barometer foam/covering against prop wash, and the EKF height reference setting.",
    "mag": "Recalibrate the compass away from metal and check for interference from power wires or the battery.",
    "airspeed": "Check the pitot tube for blockage and recalibrate the airspeed sensor.",
    "range": "Check the range finder mounting, orientation and that it isn't seeing the landing gear.",
    "flow": "Check the optical flow lens, mounting orientation and that there is enough light and ground texture.",
}
# extra advice that names a parameter, per autopilot: (sentence, params)
PARAM_ADVICE = {
    ("px4", "gps"): (" Make sure EKF2_GPS_DELAY matches the receiver.", ["EKF2_GPS_DELAY"]),
}
GENERIC_RATIO_ADVICE = (
    "Find which sensor this ratio belongs to and check its calibration and mounting; "
    "a ratio stuck over 1 means the EKF is ignoring that sensor."
)

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
AP_GPS_GLITCH_BIT = 14          # nav_filter_status.gps_glitching
AP_TLOG_GPS_GLITCH_BIT = 15     # EKF_STATUS_FLAGS.EKF_GPS_GLITCH

# XKF4/NKF4.FS bit -> (label, sensor group or None, severity)
AP_FAULTS = {
    0: ("Attitude Estimate Is NaN", None, Severity.CRITICAL),
    1: ("Velocity Estimate Is NaN", None, Severity.CRITICAL),
    2: ("Bad Magnetometer X Data", "mag", Severity.WARNING),
    3: ("Bad Magnetometer Y Data", "mag", Severity.WARNING),
    4: ("Bad Magnetometer Z Data", "mag", Severity.WARNING),
    5: ("Bad Airspeed Data", "airspeed", Severity.WARNING),
    6: ("Bad Synthetic Sideslip", "airspeed", Severity.WARNING),
    7: ("Filter Not Initialised", None, Severity.WARNING),
}
# XKF4/NKF4.TS. Airspeed (4) and drag (5) time out permanently on vehicles
# that don't fuse them, so they're not judged.
AP_TIMEOUTS = {
    0: ("Position", "gps"),
    1: ("Velocity", "gps"),
    2: ("Height", "height"),
    3: ("Magnetometer", "mag"),
}

# estimator_innovation_test_ratios / *_test_ratio columns that are ratios;
# anything else (timestamp, timestamp_sample, unknown fields) is ignored
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
RATIO_GROUPS = {
    "gps_hvel": "gps", "gps_vvel": "gps", "gps_hpos": "gps", "gps_vpos": "gps",
    "vel_test_ratio": "gps", "pos_test_ratio": "gps",
    "baro_vpos": "height", "hgt_test_ratio": "height",
    "rng_vpos": "range", "hagl": "range", "hagl_rate": "range", "hagl_test_ratio": "range",
    "heading": "mag", "mag_field": "mag", "mag_test_ratio": "mag",
    "airspeed": "airspeed", "tas_test_ratio": "airspeed", "beta": "airspeed", "beta_test_ratio": "airspeed",
    "flow": "flow",
}

RATIO_REJECT = 1.0
RATIO_NEAR = 0.8 ** 2           # Mission Planner's 0.8 on ArduPilot's sqrt scale
NEAR_LIMIT_MIN_S = 2.0
SUSTAINED_FAILURE_S = 0.5
INVALID_MIN_FRACTION = 0.01
WIND_CHANGE_THRESH = 5.0       # m/s in one step


def _armed_rows(df, phases, sol_col=None):
    """Rows of df in armed time; with no arming data, from the first row
    with an attitude solution on."""
    df = df.sort_values("timestamp").reset_index(drop=True)
    keep = phases.mask(df["timestamp"].to_numpy(float), "armed")
    if not phases.known and sol_col and sol_col in df.columns:
        sol = df[sol_col].to_numpy(float)
        attitude_ok = (np.nan_to_num(sol).astype(np.int64) & 1) == 1
        ok = np.flatnonzero(np.isfinite(sol) & attitude_ok)
        if len(ok):
            keep[: ok[0]] = False
    return df[keep].reset_index(drop=True)


def _bits(df, col):
    """(flags as int, timestamps) for the rows that have the column."""
    if col not in df.columns or df[col].notna().sum() <= 1:
        return None, None
    have = df[col].notna().to_numpy()
    return df[col][have].astype(np.int64).to_numpy(), df["timestamp"].to_numpy(float)[have]


class EKFAnalyser(BaseAnalyser):
    name            = "ekf"
    display_name    = "EKF Health Analysis"
    weight          = 20.0
    required_any    = ["estimator_status", "estimator_innovation_test_ratios", "ekf_test_ratios"]
    optional_topics = ["vehicle_status", "vehicle_land_detected"]

    def analyse(self, topics, params):
        phases = flight_phases(topics)
        autopilot = vehicle_from_params(params).autopilot
        self._autopilot = autopilot

        est = topics.get("estimator_status")
        if est is not None and "timestamp" in est.columns:
            est = _armed_rows(est, phases, "solution_status_flags")
        else:
            est = None
        ap = topics.get("ekf_test_ratios")
        if ap is not None and "timestamp" in ap.columns:
            ap = _armed_rows(ap, phases, "solution_status" if "solution_status" in ap.columns else "flags")
        else:
            ap = None

        ratio_df = topics.get("estimator_innovation_test_ratios")
        if ratio_df is not None and "timestamp" in ratio_df.columns:
            ratio_df = ratio_df.sort_values("timestamp")
            ratio_df = ratio_df[phases.mask(ratio_df["timestamp"].to_numpy(float), "armed")]
        elif est is not None and any(c.endswith("_test_ratio") for c in est.columns):
            ratio_df = est
        else:
            ratio_df = ap

        n_est = len(est) if est is not None else 0
        n_ap = len(ap) if ap is not None else 0
        n_ratio = len(ratio_df) if ratio_df is not None else 0
        if n_est < 2 and n_ap < 2 and n_ratio < 2:
            return self._skip(f"No EKF status samples {phases.describe('armed')}.")

        findings: list[Finding] = []
        health_score = 100.0

        if n_est > 1:
            # a missing flags sample is no data, not "every bit clear"
            flags, t = _bits(est, "innovation_check_flags")
            if flags is not None:
                f, p = self._innov_flags(flags, t)
                findings += f
                health_score -= min(p, 60.0)
            sol, t = _bits(est, "solution_status_flags")
            if sol is not None:
                f, p = self._solution_flags(sol, t, "solution_status_flags", GPS_GLITCH_BIT, ACCEL_ERROR_BIT)
                findings += f
                health_score -= min(p, 45.0)

        if n_ap > 1:
            sol, t = _bits(ap, "solution_status")
            if sol is not None:
                f, p = self._solution_flags(sol, t, "XKF4.SS", AP_GPS_GLITCH_BIT, None)
            else:
                sol, t = _bits(ap, "flags")
                if sol is None:
                    f, p = [], 0.0
                elif autopilot == "px4":
                    f, p = self._solution_flags(sol, t, "ESTIMATOR_STATUS flags", GPS_GLITCH_BIT, ACCEL_ERROR_BIT)
                else:
                    f, p = self._solution_flags(sol, t, "EKF_STATUS_REPORT flags", AP_TLOG_GPS_GLITCH_BIT, None)
            findings += f
            health_score -= min(p, 45.0)

            fault, t = _bits(ap, "fault_status")
            if fault is not None:
                f, p = self._ap_faults(fault, t)
                findings += f
                health_score -= min(p, 45.0)
            tmo, t = _bits(ap, "timeout_status")
            if tmo is not None:
                f, p = self._ap_timeouts(tmo, t)
                findings += f
                health_score -= min(p, 30.0)

        groups = {}
        if n_ratio > 1:
            groups = self._ratio_groups(ratio_df)
            f, p = self._innov_ratios(groups, ratio_df["timestamp"].to_numpy(float))
            findings += f
            health_score -= min(p, 30.0)

        if n_est > 1:
            wn = find_col(est, ["wind_vel_n", "wind[0]"])
            we = find_col(est, ["wind_vel_e", "wind[1]"])
            if wn and we:
                f, p = self._wind(est[wn].to_numpy(float), est[we].to_numpy(float),
                                  est["timestamp"].to_numpy(float))
                findings += f
                health_score -= p

        if groups:
            chart_ts = ratio_df["timestamp"].to_numpy(float)
            names = list(groups)
            chart_ts_ms, *vals = downsample(chart_ts, *(groups[n] for n in names))
            chart_data = {"timestamps": chart_ts_ms, "innov_ratios": dict(zip(names, vals))}
        else:
            base = next(d for d in (est, ap, ratio_df) if d is not None and len(d) > 1)
            chart_data = {"timestamps": downsample(base["timestamp"].to_numpy(float))[0], "innov_ratios": {}}
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

    def _advice(self, group):
        """(recommendation, params) for a sensor group."""
        text = SENSOR_ADVICE.get(group, GENERIC_RATIO_ADVICE)
        extra, params = PARAM_ADVICE.get((getattr(self, "_autopilot", "unknown"), group), ("", []))
        return text + extra, list(params)

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
            rec, names = self._advice(group)
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING if sustained else Severity.INFO,
                kind="ekf.innovation_rejected",
                title=f"EKF Innovation Failure: {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation=rec,
                params=names,
                confidence=confidence(longest / SUSTAINED_FAILURE_S - 1, longest),
                **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
            ))
        return findings, penalty

    def _solution_flags(self, sol, ts, source, glitch_bit, accel_bit):
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
                f"({int(bad.sum())} samples, longest {longest:.1f}s; {source} bit {bit})."
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

        checks = [
            (glitch_bit, "ekf.gps_glitch", "EKF Detected a GPS Glitch", Severity.WARNING,
             "The EKF saw GPS jump away from its own estimate. Check for multipath near structures and GPS interference; review the flight path at that time."),
            (accel_bit, "ekf.accel_error", "EKF Detected Bad Accelerometer Data", Severity.CRITICAL,
             "Bad accelerometer data usually means clipping from heavy vibration. Check props, motor mounts and flight-controller damping before flying again."),
        ]
        for bit, kind, title, sev, rec in checks:
            if bit is None:
                continue
            on = (sol & (1 << bit)) != 0
            if not on.any():
                continue
            runs = find_runs(on)
            longest = max(run_seconds(ts, a, b) for a, b in runs)
            penalty += 30.0 if sev == Severity.CRITICAL else 15.0
            tech = (
                f"{source} bit {bit} set in {int(on.sum())} of {n} armed samples "
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

    def _ap_faults(self, fs, ts):
        findings, penalty = [], 0.0
        for bit, (label, group, sev) in AP_FAULTS.items():
            on = (fs & (1 << bit)) != 0
            if not on.any():
                continue
            runs = find_runs(on)
            longest = max(run_seconds(ts, a, b) for a, b in runs)
            penalty += 30.0 if sev == Severity.CRITICAL else 15.0
            tech = (
                f"EKF fault status (XKF4.FS) bit {bit} set in {int(on.sum())} armed samples "
                f"({len(runs)} episode(s), longest {longest:.1f}s)."
            )
            if group:
                rec, names = self._advice(group)
            else:
                rec, names = ("Don't fly again until the cause is found: check IMU health, vibration and "
                              "the EKF messages around that time."), []
            findings.append(Finding(
                category=Category.EKF,
                severity=sev,
                kind="ekf.filter_fault",
                title=f"EKF Fault: {label}",
                technical_summary=tech,
                plain_english=tech,
                recommendation=rec,
                params=names,
                confidence=confidence(len(runs) / 3.0, longest),
                **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
            ))
        return findings, penalty

    def _ap_timeouts(self, tmo, ts):
        findings, penalty = [], 0.0
        for bit, (label, group) in AP_TIMEOUTS.items():
            on = (tmo & (1 << bit)) != 0
            clear = np.flatnonzero(~on)
            if not len(clear):
                continue    # never received at all (no GPS indoors, no compass): not a dropout
            on = on[clear[0]:]
            t = ts[clear[0]:]
            if not on.any():
                continue
            runs = find_runs(on)
            longest = max(run_seconds(t, a, b) for a, b in runs)
            if longest < SUSTAINED_FAILURE_S:
                continue
            penalty += 15.0
            tech = (
                f"EKF stopped receiving usable {label.lower()} measurements while armed "
                f"(XKF4.TS bit {bit}, {len(runs)} episode(s), longest {longest:.1f}s)."
            )
            rec, names = self._advice(group)
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING,
                kind="ekf.sensor_timeout",
                title=f"EKF {label} Measurement Timeout",
                technical_summary=tech,
                plain_english=tech,
                recommendation=rec,
                params=names,
                confidence=confidence(longest / SUSTAINED_FAILURE_S - 1, longest),
                **when(t[runs[0][0]], t[min(runs[-1][1], len(t) - 1)]),
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
            label = RATIO_LABELS.get(base, base.replace("_", " ").title()[:40])
            group = RATIO_GROUPS.get(base)
            rec, names = self._advice(group) if group else (GENERIC_RATIO_ADVICE, [])
            failed = v > RATIO_REJECT
            if not failed.any():
                f = self._near_limit(label, v, ts, rec, names, base)
                if f is not None:
                    penalty += 10.0
                    findings.append(f)
                continue
            runs = find_runs(failed)
            durs = [run_seconds(ts, a, b) for a, b in runs]
            longest = max(durs)
            sustained = longest >= SUSTAINED_FAILURE_S
            penalty += 15.0 if sustained else 5.0
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
                recommendation=rec,
                params=names,
                confidence=confidence(float(np.nanmax(v)) - 1, longest),
                chart_data=dict(zip(["timestamps", "ratio"], downsample(ts, v)), col=base),
                **when(ts[a], ts[min(b, len(ts) - 1)]),
            ))
        return findings, penalty

    def _near_limit(self, label, v, ts, rec, names, base):
        high = v > RATIO_NEAR
        if not high.any():
            return None
        runs = find_runs(high)
        durs = [run_seconds(ts, a, b) for a, b in runs]
        longest = max(durs)
        if longest < NEAR_LIMIT_MIN_S:
            return None
        peak = float(np.nanmax(v))
        tech = (
            f"{label} innovation test ratio stayed above {RATIO_NEAR:.2f} (0.8 on the square-root "
            f"scale Mission Planner shows) for up to {longest:.1f}s while armed; peak {peak:.2f}. "
            f"Close to the 1.0 where the EKF starts rejecting it."
        )
        a, b = runs[int(np.argmax(durs))]
        return Finding(
            category=Category.EKF,
            severity=Severity.WARNING,
            kind="ekf.innovation_ratio_high",
            title=f"EKF Innovation Ratio Near Limit: {label}",
            technical_summary=tech,
            plain_english=tech,
            recommendation=rec,
            params=names,
            confidence=confidence(peak / RATIO_NEAR - 1, longest),
            chart_data=dict(zip(["timestamps", "ratio"], downsample(ts, v)), col=base),
            **when(ts[a], ts[min(b, len(ts) - 1)]),
        )

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
