"""
Tests for VibrationAnalyser — IMU RMS and clip analysis.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.vibration import VibrationAnalyser
from flightmd_core.models.findings import Severity


def make_accel_df(rms: float, n: int = 2000, clip_count: int = 0) -> pd.DataFrame:
    """Generate a sensor_accel DataFrame with a given RMS level."""
    rng = np.random.default_rng(42)
    std = rms / np.sqrt(3)   # equal contribution across 3 axes
    x = rng.normal(0, std, n)
    y = rng.normal(0, std, n)
    z = rng.normal(0, std, n)
    # Inject hard clips
    if clip_count > 0:
        indices = rng.choice(n, clip_count, replace=False)
        x[indices] = 35.0   # above 30 m/s² clip threshold
    ts = np.arange(n) * 4000   # 4ms steps → 250 Hz
    return pd.DataFrame({"timestamp": ts, "x": x, "y": y, "z": z})


def make_topics(df: pd.DataFrame, key: str = "sensor_accel") -> dict:
    return {key: df, "sensor_accel": df}


class TestVibrationAnalyser:

    def test_low_vibration_no_findings(self):
        """RMS well below 30 m/s² → no findings."""
        df = make_accel_df(rms=10.0)
        result = VibrationAnalyser().safe_analyse(make_topics(df), {})
        assert not result.skipped
        assert len(result.findings) == 0
        assert result.health_score == 100.0

    def test_warning_vibration(self):
        """RMS between 30–60 m/s² → WARNING finding."""
        df = make_accel_df(rms=45.0)
        result = VibrationAnalyser().safe_analyse(make_topics(df), {})
        assert len(result.findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_critical_vibration(self, high_vibration_accel):
        """RMS > 60 m/s² → CRITICAL finding."""
        result = VibrationAnalyser().safe_analyse(
            make_topics(high_vibration_accel), {}
        )
        assert len(result.findings) >= 1
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_hard_clipping_detected(self):
        """More than 100 samples above ±30 m/s² → clipping WARNING."""
        df = make_accel_df(rms=15.0, clip_count=200)
        result = VibrationAnalyser().safe_analyse(make_topics(df), {})
        clip_findings = [f for f in result.findings if "clip" in f.title.lower()]
        assert len(clip_findings) >= 1

    def test_health_score_penalised_on_critical(self, high_vibration_accel):
        result = VibrationAnalyser().safe_analyse(
            make_topics(high_vibration_accel), {}
        )
        assert result.health_score < 100.0

    def test_chart_data_present(self, high_vibration_accel):
        result = VibrationAnalyser().safe_analyse(
            make_topics(high_vibration_accel), {}
        )
        for f in result.findings:
            if f.chart_data:
                assert "x" in f.chart_data or "instances" in f.chart_data

    def test_multi_imu_consistency(self):
        """Two IMUs with very different RMS → consistency WARNING."""
        df_low  = make_accel_df(rms=5.0)
        df_high = make_accel_df(rms=40.0)
        topics = {
            "sensor_accel":   df_low,
            "sensor_accel_0": df_low,
            "sensor_accel_1": df_high,
        }
        result = VibrationAnalyser().safe_analyse(topics, {})
        consistency_findings = [
            f for f in result.findings if "inconsistency" in f.title.lower()
            or "disagree" in f.technical_summary.lower()
        ]
        assert len(consistency_findings) >= 1

    def test_missing_topic_skipped(self):
        analyser = VibrationAnalyser()
        assert not analyser.is_applicable(set())

    def test_confidence_in_range(self):
        df = make_accel_df(rms=70.0)
        result = VibrationAnalyser().safe_analyse(make_topics(df), {})
        for f in result.findings:
            assert 0.0 <= f.confidence <= 1.0

    def test_category_is_vibration(self):
        from flightmd_core.models.findings import Category
        df = make_accel_df(rms=50.0)
        result = VibrationAnalyser().safe_analyse(make_topics(df), {})
        for f in result.findings:
            assert f.category == Category.VIBRATION
