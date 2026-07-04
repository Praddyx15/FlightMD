"""
EKFAnalyser — EKF health, innovation spikes, and solution validity.

The EKF (Extended Kalman Filter) fuses GPS, IMU, magnetometer, barometer
and other sensors to produce a state estimate. Innovation test failures mean
the EKF doesn't trust a sensor — a precursor to estimation divergence.
"""

import numpy as np
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# innovation_check_flags bitmask definitions
INNOV_FLAG_NAMES = {
    0:  "velocity_x_innovation",
    1:  "velocity_y_innovation",
    2:  "velocity_z_innovation",
    3:  "horizontal_position_innovation",
    4:  "vertical_position_innovation",
    5:  "magnetometer_x_innovation",
    6:  "magnetometer_y_innovation",
    7:  "magnetometer_z_innovation",
    8:  "heading_innovation",
    9:  "airspeed_innovation",
    10: "sideslip_innovation",
    11: "height_above_ground_innovation",
    12: "optical_flow_x_innovation",
    13: "optical_flow_y_innovation",
    14: "optical_flow_quality_innovation",
    15: "optical_flow_gyro_innovation",
}

# solution_status_flags definitions
SOLUTION_FLAG_NAMES = {
    0: "attitude_estimate_valid",
    1: "horizontal_velocity_valid",
    2: "vertical_velocity_valid",
    3: "relative_position_valid",
    4: "absolute_position_valid",
    5: "gps_available",
}

# Sustained innovation failure threshold (seconds)
SUSTAINED_FAILURE_THRESH_S = 0.5

# Wind speed change threshold (m/s in single step)
WIND_CHANGE_THRESH = 5.0


class EKFAnalyser(BaseAnalyser):
    name            = "ekf"
    display_name    = "EKF Health Analysis"
    required_topics = ["estimator_status"]
    optional_topics = ["estimator_innovation_test_ratios", "estimator_sensor_bias"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        df = topics["estimator_status"].copy()
        findings: list[Finding] = []
        health_score = 100.0

        # Estimate sample rate
        sample_rate = self._sample_rate(df)

        # ── 1. Innovation check flags bitmask ────────────────────────────────
        if "innovation_check_flags" in df.columns:
            flags = df["innovation_check_flags"].fillna(0).astype(int)
            flag_findings, flag_score_penalty = self._analyse_innov_flags(
                flags, df.get("timestamp"), sample_rate
            )
            findings.extend(flag_findings)
            health_score = max(0.0, health_score - flag_score_penalty)

        # ── 2. Solution status flags ─────────────────────────────────────────
        if "solution_status_flags" in df.columns:
            sol_flags = df["solution_status_flags"].fillna(0).astype(int)
            sol_findings, sol_penalty = self._analyse_solution_flags(
                sol_flags, df.get("timestamp")
            )
            findings.extend(sol_findings)
            health_score = max(0.0, health_score - sol_penalty)

        # ── 3. Innovation test ratios (detailed) ─────────────────────────────
        if "estimator_innovation_test_ratios" in topics:
            ratio_df = topics["estimator_innovation_test_ratios"].copy()
            ratio_findings, ratio_penalty = self._analyse_innov_ratios(
                ratio_df, sample_rate
            )
            findings.extend(ratio_findings)
            health_score = max(0.0, health_score - ratio_penalty)

        # ── 4. Wind estimation anomalies ─────────────────────────────────────
        wind_n_col = self._find_col(df, ["wind_vel_n", "wind[0]"])
        wind_e_col = self._find_col(df, ["wind_vel_e", "wind[1]"])
        if wind_n_col and wind_e_col:
            wind_findings, wind_penalty = self._analyse_wind(
                df[wind_n_col].values, df[wind_e_col].values, df.get("timestamp")
            )
            findings.extend(wind_findings)
            health_score = max(0.0, health_score - wind_penalty)

        # Build combined chart data from estimator_status
        chart_data = self._build_chart_data(df, topics)

        # Attach chart_data to all findings in this analyser
        for f in findings:
            if f.chart_data is None:
                f.chart_data = chart_data

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
        )

    # ── private helpers ──────────────────────────────────────────────────────

    def _sample_rate(self, df: pd.DataFrame) -> float:
        if "timestamp" in df.columns and len(df) > 1:
            dt = df["timestamp"].diff().median()
            return 1e6 / dt if dt > 0 else 50.0
        return 50.0

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _analyse_innov_flags(
        self,
        flags: pd.Series,
        timestamps: Optional[pd.Series],
        sample_rate: float,
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        total_penalty = 0.0

        for bit, name in INNOV_FLAG_NAMES.items():
            bit_set = (flags & (1 << bit)) != 0
            set_count = int(bit_set.sum())
            if set_count == 0:
                continue

            # Find contiguous runs
            runs = self._find_runs(bit_set.values)
            max_run_samples = max(r[1] - r[0] for r in runs) if runs else 0
            max_run_s = max_run_samples / sample_rate

            if max_run_s >= SUSTAINED_FAILURE_THRESH_S:
                sev = Severity.WARNING
                penalty = 15.0
            else:
                sev = Severity.INFO
                penalty = 5.0

            total_penalty += penalty

            ts_start = None
            ts_end   = None
            if timestamps is not None and runs:
                ts_arr = timestamps.values
                ts_start = int(ts_arr[runs[0][0]] / 1e3) if runs[0][0] < len(ts_arr) else None
                ts_end   = int(ts_arr[runs[-1][1]-1] / 1e3) if runs[-1][1]-1 < len(ts_arr) else None

            tech = (
                f"EKF innovation check failed for '{name}': "
                f"{set_count} samples flagged, longest run {max_run_s:.2f}s."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=sev,
                title=f"EKF Innovation Failure: {name.replace('_', ' ').title()}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Review sensor calibration and check for magnetic interference or GPS obstructions.",
                confidence=min(1.0, set_count / len(flags)),
                timestamp_start_ms=ts_start,
                timestamp_end_ms=ts_end,
            ))

        return findings, min(total_penalty, 60.0)   # cap at 60 per category

    def _analyse_solution_flags(
        self,
        sol_flags: pd.Series,
        timestamps: Optional[pd.Series],
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        total_penalty = 0.0

        for bit, name in SOLUTION_FLAG_NAMES.items():
            bit_valid = (sol_flags & (1 << bit)) != 0
            invalid_count = int((~bit_valid).sum())
            if invalid_count == 0:
                continue

            pct_invalid = invalid_count / len(sol_flags) * 100
            if pct_invalid < 1.0:
                continue   # transient, ignore

            total_penalty += 15.0
            tech = (
                f"EKF solution flag '{name}' invalid for {pct_invalid:.1f}% of flight "
                f"({invalid_count} samples)."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING,
                title=f"EKF Solution Invalid: {name.replace('_', ' ').title()}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Check sensor health and ensure proper pre-flight calibration before the next flight.",
                confidence=min(1.0, pct_invalid / 10.0),
            ))

        return findings, min(total_penalty, 45.0)

    def _analyse_innov_ratios(
        self,
        ratio_df: pd.DataFrame,
        sample_rate: float,
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        total_penalty = 0.0

        ratio_cols = [c for c in ratio_df.columns if c != "timestamp"]
        for col in ratio_cols:
            vals = ratio_df[col].dropna()
            if len(vals) == 0:
                continue
            failed = vals > 1.0
            if not failed.any():
                continue

            runs = self._find_runs(failed.values)
            max_run_s = max((r[1] - r[0]) for r in runs) / sample_rate if runs else 0.0

            if max_run_s >= SUSTAINED_FAILURE_THRESH_S:
                sev = Severity.WARNING
                penalty = 15.0
            else:
                sev = Severity.INFO
                penalty = 5.0

            total_penalty += penalty
            tech = (
                f"Innovation test ratio for '{col}' exceeded 1.0 (test failed) for "
                f"{failed.sum()} samples. Longest sustained failure: {max_run_s:.2f}s."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=sev,
                title=f"EKF Innovation Ratio Exceeded: {col}",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Inspect sensor fusion settings. Consider recalibrating the affected sensor.",
                confidence=min(1.0, float(failed.mean()) * 5),
                chart_data={
                    "timestamps": (ratio_df["timestamp"].values / 1e3).tolist()
                    if "timestamp" in ratio_df.columns else [],
                    "ratio": vals.tolist(),
                    "col": col,
                },
            ))

        return findings, min(total_penalty, 30.0)

    def _analyse_wind(
        self,
        wind_n: np.ndarray,
        wind_e: np.ndarray,
        timestamps: Optional[pd.Series],
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        penalty = 0.0

        wind_speed = np.sqrt(wind_n**2 + wind_e**2)
        delta = np.abs(np.diff(wind_speed))
        jump_mask = delta > WIND_CHANGE_THRESH

        if jump_mask.any():
            max_jump = float(delta.max())
            jump_count = int(jump_mask.sum())
            penalty = 10.0
            tech = (
                f"EKF wind estimate changed by >{WIND_CHANGE_THRESH} m/s in a single step. "
                f"Max jump: {max_jump:.1f} m/s. Occurrences: {jump_count}."
            )
            findings.append(Finding(
                category=Category.EKF,
                severity=Severity.WARNING,
                title="Unexpected Wind Estimation Jump",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Sudden wind jumps may indicate GPS anomaly or sudden airspeed sensor dropout. Review GPS and pitot data.",
                confidence=min(1.0, max_jump / 15.0),
            ))

        return findings, penalty

    def _find_runs(self, bool_array: np.ndarray) -> list[tuple[int, int]]:
        """Return list of (start, end) index pairs for True runs."""
        runs = []
        in_run = False
        start = 0
        for i, v in enumerate(bool_array):
            if v and not in_run:
                in_run = True
                start = i
            elif not v and in_run:
                in_run = False
                runs.append((start, i))
        if in_run:
            runs.append((start, len(bool_array)))
        return runs

    def _build_chart_data(
        self,
        df: pd.DataFrame,
        topics: dict[str, pd.DataFrame],
    ) -> dict:
        ts = (df["timestamp"].values / 1e3).tolist() if "timestamp" in df.columns else []
        step = max(1, len(ts) // 500)
        innov_ratios = {}

        if "estimator_innovation_test_ratios" in topics:
            ratio_df = topics["estimator_innovation_test_ratios"]
            for col in ratio_df.columns:
                if col != "timestamp":
                    innov_ratios[col] = ratio_df[col].values[::step].tolist()

        return {
            "timestamps": ts[::step],
            "innov_ratios": innov_ratios,
        }
