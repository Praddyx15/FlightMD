"""
VibrationAnalyser — IMU RMS vibration and clip analysis.

High vibration levels indicate mechanical issues: prop imbalance, loose motor
mounts, resonant frame modes. Hard clipping means the IMU is saturating —
a serious condition that corrupts EKF estimates.
"""

import numpy as np
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# RMS thresholds (m/s²)
RMS_CRITICAL = 60.0
RMS_WARNING  = 30.0

# Hard clip threshold (m/s²)
CLIP_THRESHOLD = 30.0
CLIP_COUNT_WARNING = 100

# IMU consistency: if two IMUs differ by more than this → WARNING
IMU_CONSISTENCY_THRESH = 15.0   # m/s²


class VibrationAnalyser(BaseAnalyser):
    name          = "vibration"
    display_name  = "Vibration Analysis"
    required_topics = ["sensor_accel"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        findings: list[Finding] = []
        health_score = 100.0

        # Collect all IMU instances — PX4 logs sensor_accel_0, _1, _2 etc.
        imu_dfs: list[tuple[str, pd.DataFrame]] = []
        for key in sorted(topics.keys()):
            if key.startswith("sensor_accel"):
                imu_dfs.append((key, topics[key].copy()))

        if not imu_dfs:
            return AnalyserResult(
                analyser=self.name,
                display_name=self.display_name,
                findings=[],
                skipped=True,
                skip_reason="No sensor_accel topics found in log.",
            )

        # Per-IMU analysis
        imu_rms_values: list[float] = []   # primary-axis combined RMS per IMU
        chart_data = {"instances": {}}

        for imu_name, df in imu_dfs:
            x_col = self._find_col(df, ["x", "xyz[0]"])
            y_col = self._find_col(df, ["y", "xyz[1]"])
            z_col = self._find_col(df, ["z", "xyz[2]"])

            if x_col is None:
                continue

            x = df[x_col].dropna().values if x_col else np.zeros(1)
            y = df[y_col].dropna().values if y_col else np.zeros(len(x))
            z = df[z_col].dropna().values if z_col else np.zeros(len(x))

            # Align lengths (different IMUs may have slightly different sample counts)
            min_len = min(len(x), len(y), len(z))
            x, y, z = x[:min_len], y[:min_len], z[:min_len]

            rms_x = float(np.sqrt(np.mean(x ** 2)))
            rms_y = float(np.sqrt(np.mean(y ** 2)))
            rms_z = float(np.sqrt(np.mean(z ** 2)))
            combined_rms = float(np.sqrt(np.mean(x**2 + y**2 + z**2)))

            clip_count = int(np.sum(np.abs(x) > CLIP_THRESHOLD) +
                             np.sum(np.abs(y) > CLIP_THRESHOLD) +
                             np.sum(np.abs(z) > CLIP_THRESHOLD))

            imu_rms_values.append(combined_rms)

            # Build downsampled chart data (max 500 points)
            ts = df["timestamp"].values[:min_len] if "timestamp" in df.columns else np.arange(min_len)
            step = max(1, min_len // 500)
            chart_data["instances"][imu_name] = {
                "timestamps": (ts[::step] / 1e3).tolist(),   # µs → ms
                "x": x[::step].tolist(),
                "y": y[::step].tolist(),
                "z": z[::step].tolist(),
                "rms_x": rms_x,
                "rms_y": rms_y,
                "rms_z": rms_z,
                "combined_rms": combined_rms,
                "clip_count": clip_count,
            }

            # ── Severity by RMS ──────────────────────────────────────────────
            if combined_rms > RMS_CRITICAL:
                severity = Severity.CRITICAL
                health_score = max(0.0, health_score - 30)
                tech = (
                    f"{imu_name}: combined RMS={combined_rms:.1f} m/s² (CRITICAL, threshold={RMS_CRITICAL}). "
                    f"Per-axis: X={rms_x:.1f}, Y={rms_y:.1f}, Z={rms_z:.1f} m/s²."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=severity,
                    title=f"Critical Vibration — {imu_name.replace('_', ' ').title()}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Immediately inspect propellers for balance/damage. Check all motor bell screws and frame arm bolts.",
                    confidence=min(1.0, combined_rms / 100.0),
                    chart_data={"instance": imu_name, **chart_data["instances"][imu_name]},
                ))

            elif combined_rms > RMS_WARNING:
                severity = Severity.WARNING
                health_score = max(0.0, health_score - 15)
                tech = (
                    f"{imu_name}: combined RMS={combined_rms:.1f} m/s² (WARNING, threshold={RMS_WARNING}). "
                    f"Per-axis: X={rms_x:.1f}, Y={rms_y:.1f}, Z={rms_z:.1f} m/s²."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=severity,
                    title=f"Elevated Vibration — {imu_name.replace('_', ' ').title()}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Balance propellers using a prop balancer. Inspect motor mounts for looseness.",
                    confidence=min(1.0, combined_rms / 80.0),
                    chart_data={"instance": imu_name, **chart_data["instances"][imu_name]},
                ))

            # ── Hard clipping ────────────────────────────────────────────────
            if clip_count > CLIP_COUNT_WARNING:
                health_score = max(0.0, health_score - 15)
                tech = (
                    f"{imu_name}: {clip_count} samples exceed clip threshold of ±{CLIP_THRESHOLD} m/s². "
                    f"IMU saturation corrupts EKF attitude estimates."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.WARNING,
                    title=f"Hard IMU Clipping Detected — {imu_name.replace('_', ' ').title()}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Loose prop or motor bell likely. Check all prop nuts are tight. Add vibration damping foam under flight controller.",
                    confidence=min(1.0, clip_count / 500.0),
                    chart_data={"instance": imu_name, **chart_data["instances"][imu_name]},
                ))

        # ── Multi-IMU consistency ────────────────────────────────────────────
        if len(imu_rms_values) >= 2:
            rms_spread = max(imu_rms_values) - min(imu_rms_values)
            if rms_spread > IMU_CONSISTENCY_THRESH:
                health_score = max(0.0, health_score - 15)
                tech = (
                    f"IMU instances disagree: max RMS spread = {rms_spread:.1f} m/s² "
                    f"(threshold = {IMU_CONSISTENCY_THRESH} m/s²). "
                    f"Per-instance RMS: {[round(v, 1) for v in imu_rms_values]}."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.WARNING,
                    title="IMU Instance Inconsistency",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Check flight controller mounting. One IMU may be poorly isolated from vibration path.",
                    confidence=min(1.0, rms_spread / 30.0),
                    chart_data=chart_data,
                ))

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
        )

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None
