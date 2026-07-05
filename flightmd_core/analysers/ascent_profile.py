"""
AscentProfileAnalyser — apogee detection, high-G launch profile, and
parachute deployment detection for single-apogee ballistic flights:
sounding rockets and high-altitude balloons.

Most flights FlightMD analyses are multirotor survey/mapping missions
with many climb/descend cycles. This analyser is scoped specifically to
flights with a single dominant altitude peak — one continuous ascent,
one continuous descent — and detects that shape itself from the GPS
altitude trace, rather than trusting a declared vehicle type. ArduPilot
has no "Rocket" firmware; sounding rockets and HABs typically fly
Plane-mode ArduPilot, a custom flight computer streaming MAVLink, or no
recognisable autopilot label at all, so `metadata.vehicle_type` can't be
trusted to gate this. When the altitude trace doesn't have that shape,
this analyser skips gracefully — not an error, the same way
MotorAnalyser skips when ESC telemetry isn't present.

Not included in score_calculator.MODULE_WEIGHTS: it's inapplicable to
the vast majority of flights, and its safety-relevant-but-narrow
findings (e.g. "no parachute deployment detected") shouldn't dilute or
be diluted by the general multirotor scoring.
"""

from typing import Optional

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import AnalyserResult, Finding, Severity, Category

G = 9.80665  # m/s², standard gravity

# A flight qualifies as "single-apogee" if find_peaks on the altitude
# trace (with this prominence, relative to total altitude range) finds
# exactly one peak. A multirotor survey mission's repeated climb/descend
# cycles will trip this well before a genuine rocket/HAB profile does.
PEAK_PROMINENCE_FRACTION = 0.15
MIN_PROMINENCE_M = 5.0

LAUNCH_G_THRESHOLD = 2.5 * G     # sustained accel above this = powered boost
MIN_BOOST_DURATION_S = 0.2

# Asymmetric-loading (tumbling during boost) — coefficient of variation
# of gyro-rate magnitude within the boost window.
ASYMMETRIC_LOADING_CV_WARNING = 0.6

# Deployment = descent speed drops by at least this factor within a short
# window. A stable parachute descent is dramatically slower than ballistic
# freefall/tumble, so this doesn't need to be a subtle threshold.
DEPLOYMENT_SPEED_RATIO = 2.5
DEPLOYMENT_WINDOW_S = 3.0

# Only claim "no deployment detected" if the log's descent actually
# reaches close to the ground — otherwise the log may simply have ended
# mid-descent (telemetry loss), which is a different, unprovable claim.
LANDING_ALTITUDE_FRACTION = 0.1
LOW_DEPLOYMENT_ALTITUDE_FRACTION = 0.1

# A single altitude peak alone isn't enough to call a flight "ballistic" —
# an ordinary "climb up, come back down" multirotor test flight has that
# same shape. Require the apogee to also be at a scale no consumer drone
# realistically reaches in one hop (generous margin below real HAB/rocket
# altitudes, which are typically >1km), OR a genuine high-G boost phase —
# either one is a strong rocket/HAB signature that random drone flights
# essentially never produce.
MIN_QUALIFYING_APOGEE_M = 300.0


class AscentProfileAnalyser(BaseAnalyser):
    name            = "ascent_profile"
    display_name    = "Ascent & Recovery Analysis"
    required_topics = ["vehicle_gps_position"]
    optional_topics = ["sensor_accel", "vehicle_angular_velocity"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        gps_df = topics["vehicle_gps_position"]
        if "alt" not in gps_df.columns or "timestamp" not in gps_df.columns:
            return AnalyserResult(
                analyser=self.name, display_name=self.display_name,
                findings=[], skipped=True,
                skip_reason="GPS topic missing altitude or timestamp data.",
            )

        df = gps_df[["timestamp", "alt"]].dropna().sort_values("timestamp").reset_index(drop=True)
        if len(df) < 10:
            return AnalyserResult(
                analyser=self.name, display_name=self.display_name,
                findings=[], skipped=True,
                skip_reason="Not enough GPS samples to characterise a flight profile.",
            )

        ts_s = df["timestamp"].values / 1e6
        alt_m = df["alt"].values / 1000.0  # stored in mm across all 3 formats

        apogee_idx = self._find_apogee(alt_m)
        if apogee_idx is None:
            return AnalyserResult(
                analyser=self.name, display_name=self.display_name,
                findings=[], skipped=True,
                skip_reason=(
                    "Altitude profile doesn't show a single dominant peak — this analyser is "
                    "scoped to single-apogee ballistic flights (sounding rockets, high-altitude "
                    "balloons), not multi-leg missions."
                ),
            )

        launch_alt_m = alt_m[0]
        apogee_agl_m = float(alt_m[apogee_idx] - launch_alt_m)
        time_to_apogee_s = float(ts_s[apogee_idx] - ts_s[0])
        descent_duration_s = float(ts_s[-1] - ts_s[apogee_idx])
        final_agl_m = float(alt_m[-1] - launch_alt_m)

        # A single altitude peak alone doesn't distinguish a rocket/HAB from
        # an ordinary drone flight that just climbed and came back down —
        # require altitude scale or a genuine high-G boost too.
        launch_findings: list[Finding] = []
        launch_metrics: dict[str, float] = {}
        if "sensor_accel" in topics:
            launch_findings, launch_metrics = self._analyse_launch(
                topics["sensor_accel"], topics.get("vehicle_angular_velocity"),
                ts_s[0], ts_s[apogee_idx],
            )
        boost_detected = "peak_boost_g" in launch_metrics

        if apogee_agl_m < MIN_QUALIFYING_APOGEE_M and not boost_detected:
            return AnalyserResult(
                analyser=self.name, display_name=self.display_name,
                findings=[], skipped=True,
                skip_reason=(
                    f"Single altitude peak at {apogee_agl_m:.0f}m AGL with no high-G boost "
                    f"phase — within range of an ordinary drone flight, not scoped as a "
                    f"rocket/HAB ascent profile."
                ),
            )

        findings: list[Finding] = list(launch_findings)
        key_metrics: dict[str, float] = {
            "apogee_altitude_m": round(apogee_agl_m, 1),
            "time_to_apogee_s": round(time_to_apogee_s, 1),
            **launch_metrics,
        }

        tech = (
            f"Apogee reached at {apogee_agl_m:.0f}m AGL, {time_to_apogee_s:.1f}s after launch. "
            f"Descent phase lasted {descent_duration_s:.1f}s."
        )
        findings.append(Finding(
            category=Category.ASCENT_PROFILE,
            severity=Severity.GOOD,
            title=f"Apogee Detected at {apogee_agl_m:.0f}m AGL",
            technical_summary=tech,
            plain_english=tech,
            recommendation="No action needed — this is a factual measurement of the flight profile.",
            confidence=1.0,
            timestamp_start_ms=int(ts_s[apogee_idx] * 1000),
        ))

        # ── Parachute deployment ─────────────────────────────────────────────
        deploy_findings, deploy_metrics = self._analyse_deployment(
            ts_s[apogee_idx:], alt_m[apogee_idx:] - launch_alt_m, apogee_agl_m, final_agl_m,
        )
        findings.extend(deploy_findings)
        key_metrics.update(deploy_metrics)

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            key_metrics=key_metrics,
        )

    # ── shape detection ──────────────────────────────────────────────────────

    def _find_apogee(self, alt_m: np.ndarray) -> Optional[int]:
        alt_range = float(alt_m.max() - alt_m.min())
        if alt_range < MIN_PROMINENCE_M:
            return None
        prominence = max(MIN_PROMINENCE_M, alt_range * PEAK_PROMINENCE_FRACTION)
        peaks, _ = find_peaks(alt_m, prominence=prominence)
        if len(peaks) != 1:
            return None
        return int(peaks[0])

    # ── launch phase ─────────────────────────────────────────────────────────

    def _analyse_launch(
        self,
        accel_df: pd.DataFrame,
        gyro_df: Optional[pd.DataFrame],
        start_s: float,
        apogee_s: float,
    ) -> tuple[list[Finding], dict[str, float]]:
        x_col = self._find_col(accel_df, ["x", "xyz[0]"])
        y_col = self._find_col(accel_df, ["y", "xyz[1]"])
        z_col = self._find_col(accel_df, ["z", "xyz[2]"])
        if not (x_col and y_col and z_col) or "timestamp" not in accel_df.columns:
            return [], {}

        ts_s = accel_df["timestamp"].values / 1e6
        mag = np.sqrt(accel_df[x_col].values ** 2 + accel_df[y_col].values ** 2 + accel_df[z_col].values ** 2)

        ascent_mask = (ts_s >= start_s) & (ts_s <= apogee_s)
        if not ascent_mask.any():
            return [], {}

        boost_mask = ascent_mask & (mag > LAUNCH_G_THRESHOLD)
        runs = self._find_runs(boost_mask)
        if not runs:
            return [], {}

        # Longest boost run
        run_start, run_end = max(runs, key=lambda r: r[1] - r[0])
        boost_duration_s = float(ts_s[run_end - 1] - ts_s[run_start])
        if boost_duration_s < MIN_BOOST_DURATION_S:
            return [], {}

        peak_g = float(mag[run_start:run_end].max() / G)
        key_metrics = {
            "peak_boost_g": round(peak_g, 2),
            "boost_duration_s": round(boost_duration_s, 2),
        }

        tech = f"Peak acceleration {peak_g:.1f}g sustained for {boost_duration_s:.1f}s during ascent."
        findings = [Finding(
            category=Category.ASCENT_PROFILE,
            severity=Severity.GOOD,
            title=f"High-G Launch Detected ({peak_g:.1f}g)",
            technical_summary=tech,
            plain_english=tech,
            recommendation="No action needed — this is a factual measurement of the boost phase.",
            confidence=1.0,
            timestamp_start_ms=int(ts_s[run_start] * 1000),
            timestamp_end_ms=int(ts_s[run_end - 1] * 1000),
        )]

        if gyro_df is not None and "timestamp" in gyro_df.columns:
            findings.extend(self._analyse_boost_stability(
                gyro_df, ts_s[run_start], ts_s[run_end - 1], key_metrics
            ))

        return findings, key_metrics

    def _analyse_boost_stability(
        self,
        gyro_df: pd.DataFrame,
        boost_start_s: float,
        boost_end_s: float,
        key_metrics: dict[str, float],
    ) -> list[Finding]:
        roll_col  = self._find_col(gyro_df, ["rollspeed", "xyz[0]", "x"])
        pitch_col = self._find_col(gyro_df, ["pitchspeed", "xyz[1]", "y"])
        yaw_col   = self._find_col(gyro_df, ["yawspeed", "xyz[2]", "z"])
        if not (roll_col and pitch_col and yaw_col) or "timestamp" not in gyro_df.columns:
            return []

        ts_s = gyro_df["timestamp"].values / 1e6
        mask = (ts_s >= boost_start_s) & (ts_s <= boost_end_s)
        if mask.sum() < 5:
            return []

        rate_mag = np.sqrt(
            gyro_df[roll_col].values[mask] ** 2
            + gyro_df[pitch_col].values[mask] ** 2
            + gyro_df[yaw_col].values[mask] ** 2
        )
        mean_rate = float(rate_mag.mean())
        if mean_rate < 1e-6:
            return []
        cv = float(rate_mag.std() / mean_rate)
        key_metrics["boost_gyro_rate_cv"] = round(cv, 3)

        if cv > ASYMMETRIC_LOADING_CV_WARNING:
            tech = (
                f"Angular rate magnitude varied sharply during the boost phase "
                f"(coefficient of variation {cv:.2f}), suggesting asymmetric thrust, "
                f"fin misalignment, or tumbling under power."
            )
            return [Finding(
                category=Category.ASCENT_PROFILE,
                severity=Severity.WARNING,
                title="Asymmetric Loading During Boost",
                technical_summary=tech,
                plain_english=tech,
                recommendation=(
                    "Inspect fin alignment, motor mount, and centre-of-gravity placement "
                    "before the next launch. Review onboard video if available to confirm "
                    "whether the airframe tumbled during powered flight."
                ),
                confidence=min(1.0, cv / (ASYMMETRIC_LOADING_CV_WARNING * 2)),
            )]
        return []

    # ── parachute deployment ─────────────────────────────────────────────────

    def _analyse_deployment(
        self,
        descent_ts_s: np.ndarray,
        descent_agl_m: np.ndarray,
        apogee_agl_m: float,
        final_agl_m: float,
    ) -> tuple[list[Finding], dict[str, float]]:
        if len(descent_ts_s) < 5 or apogee_agl_m <= 0:
            return [], {}

        # Vertical speed (positive = descending), smoothed to reduce GPS noise.
        dt = np.diff(descent_ts_s)
        dt[dt <= 0] = 1e-3
        speed = -np.diff(descent_agl_m) / dt
        speed_ts = descent_ts_s[1:]

        window = max(1, int(len(speed) / 20))
        if window > 1:
            speed = pd.Series(speed).rolling(window, min_periods=1, center=True).median().values

        deployment_idx = self._find_deployment_index(speed, speed_ts)

        if deployment_idx is not None:
            deploy_agl_m = float(np.interp(speed_ts[deployment_idx], descent_ts_s, descent_agl_m))
            time_after_apogee_s = float(speed_ts[deployment_idx] - descent_ts_s[0])
            pre_rate = float(speed[max(0, deployment_idx - 3):deployment_idx + 1].mean())
            post_rate = float(speed[deployment_idx:deployment_idx + 4].mean())

            key_metrics = {
                "parachute_deployment_altitude_m": round(deploy_agl_m, 1),
                "time_from_apogee_to_deployment_s": round(time_after_apogee_s, 1),
            }

            tech = (
                f"Descent rate dropped from {pre_rate:.1f} m/s to {post_rate:.1f} m/s "
                f"at {deploy_agl_m:.0f}m AGL, {time_after_apogee_s:.1f}s after apogee."
            )
            findings = [Finding(
                category=Category.ASCENT_PROFILE,
                severity=Severity.GOOD,
                title=f"Parachute Deployment Detected at {deploy_agl_m:.0f}m AGL",
                technical_summary=tech,
                plain_english=tech,
                recommendation="No action needed — recovery event detected as expected.",
                confidence=0.9,
            )]

            if deploy_agl_m < apogee_agl_m * LOW_DEPLOYMENT_ALTITUDE_FRACTION:
                tech2 = (
                    f"Deployment occurred at only {deploy_agl_m:.0f}m AGL — "
                    f"{deploy_agl_m / apogee_agl_m * 100:.0f}% of apogee altitude. "
                    f"Little margin remained before ground impact."
                )
                findings.append(Finding(
                    category=Category.ASCENT_PROFILE,
                    severity=Severity.WARNING,
                    title="Low-Altitude Deployment",
                    technical_summary=tech2,
                    plain_english=tech2,
                    recommendation=(
                        "Review deployment trigger settings (apogee detection algorithm, "
                        "backup timer, or barometric threshold) — deployment margin was thin."
                    ),
                    confidence=0.7,
                ))
            return findings, key_metrics

        # No deployment signature found — only claim this if the descent
        # actually reached near the ground, otherwise the log may have
        # simply ended mid-descent.
        if final_agl_m <= apogee_agl_m * LANDING_ALTITUDE_FRACTION:
            tech = (
                f"No deceleration event was detected during descent from {apogee_agl_m:.0f}m AGL "
                f"to {final_agl_m:.0f}m AGL — the airframe appears to have descended ballistically "
                f"all the way down."
            )
            return [Finding(
                category=Category.ASCENT_PROFILE,
                severity=Severity.CRITICAL,
                title="No Parachute Deployment Detected",
                technical_summary=tech,
                plain_english=tech,
                recommendation=(
                    "Inspect the recovery system before the next flight — check deployment "
                    "charge/servo, apogee-detection firmware, and backup timer settings. "
                    "Do not reuse this airframe until the recovery system is verified on the bench."
                ),
                confidence=0.85,
            )], {}

        return [], {}

    def _find_deployment_index(self, speed: np.ndarray, speed_ts: np.ndarray) -> Optional[int]:
        for i in range(len(speed)):
            window_mask = (speed_ts >= speed_ts[i]) & (speed_ts <= speed_ts[i] + DEPLOYMENT_WINDOW_S)
            if window_mask.sum() < 3:
                continue
            pre = speed[i]
            post_window = speed[window_mask]
            post = float(np.median(post_window[len(post_window) // 2:]))
            if pre > 1.0 and post > 0 and pre / post >= DEPLOYMENT_SPEED_RATIO:
                return i
        return None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _find_runs(self, mask: np.ndarray) -> list[tuple[int, int]]:
        runs = []
        in_run = False
        start = 0
        for i, v in enumerate(mask):
            if v and not in_run:
                in_run, start = True, i
            elif not v and in_run:
                in_run = False
                runs.append((start, i))
        if in_run:
            runs.append((start, len(mask)))
        return runs
