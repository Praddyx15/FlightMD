"""
Tests for VibrationAnalyser — high-passed RMS, clipping, multi-IMU.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.vibration import VibrationAnalyser
from flightmd_core.models.findings import Severity, Category


def make_accel_df(rms: float, n: int = 2000, gravity: bool = False) -> pd.DataFrame:
    """White-noise vibration with the given combined RMS at 250 Hz."""
    rng = np.random.default_rng(42)
    std = rms / np.sqrt(3)
    x = rng.normal(0, std, n)
    y = rng.normal(0, std, n)
    z = rng.normal(0, std, n) - (9.81 if gravity else 0.0)
    ts = np.arange(n) * 4000
    return pd.DataFrame({"timestamp": ts, "x": x, "y": y, "z": z})


def run(topics):
    return VibrationAnalyser().safe_analyse(topics, {})


class TestVibrationAnalyser:

    def test_low_vibration_no_findings(self):
        result = run({"sensor_accel": make_accel_df(rms=10.0)})
        assert not result.skipped
        assert result.findings == []
        assert result.health_score == 100.0

    def test_gravity_is_not_vibration(self):
        """A hover reads ~9.8 m/s² on z from gravity alone; only content
        above ~5 Hz counts, like ArduPilot's VIBE."""
        df = make_accel_df(rms=3.0, gravity=True)
        df["z"] -= 25.0     # even a big steady offset isn't vibration
        result = run({"sensor_accel": df})
        assert result.findings == []
        assert result.key_metrics["max_imu_rms"] < 5.0

    def test_warning_vibration(self):
        result = run({"sensor_accel": make_accel_df(rms=45.0)})
        warn = [f for f in result.findings if f.kind == "vibration.elevated"]
        assert len(warn) == 1
        assert warn[0].severity == Severity.WARNING

    def test_critical_vibration(self, high_vibration_accel):
        result = run({"sensor_accel": high_vibration_accel})
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_one_imu_published_twice_is_scored_once(self):
        """Older parsers put the primary IMU under both sensor_accel and
        sensor_accel_0; that's one sensor, one finding, no self-comparison."""
        df = make_accel_df(rms=45.0)
        result = run({"sensor_accel": df, "sensor_accel_0": df})
        assert len(result.findings) == 1
        assert result.health_score == 85.0

    def test_aggressive_flight_is_not_clipping(self):
        """Peaks of 35 m/s² (3.5 g) are well inside any IMU's range."""
        df = make_accel_df(rms=10.0)
        idx = np.random.default_rng(1).choice(len(df), 200, replace=False)
        df.loc[idx, "x"] = 35.0
        result = run({"sensor_accel": df})
        assert not any(f.kind == "vibration.clipping" for f in result.findings)

    def test_range_limit_plateau_is_clipping(self):
        df = make_accel_df(rms=15.0)
        idx = np.random.default_rng(1).choice(len(df), 200, replace=False)
        df.loc[idx, "x"] = 156.9    # ±16 g full scale
        result = run({"sensor_accel": df})
        assert any(f.kind == "vibration.clipping" for f in result.findings)

    def test_clip_counter_column_is_used(self):
        df = make_accel_df(rms=5.0)
        for k in range(3):
            df[f"clip_counter[{k}]"] = 0
        df.loc[100:130, "clip_counter[2]"] = 1
        result = run({"sensor_accel": df})
        clip = [f for f in result.findings if f.kind == "vibration.clipping"]
        assert len(clip) == 1
        assert result.key_metrics["total_clip_count"] == 31.0

    def test_health_score_penalised_on_critical(self, high_vibration_accel):
        assert run({"sensor_accel": high_vibration_accel}).health_score < 100.0

    def test_chart_data_present(self, high_vibration_accel):
        result = run({"sensor_accel": high_vibration_accel})
        assert result.findings
        for f in result.findings:
            assert "x" in f.chart_data or "instances" in f.chart_data

    def test_multi_imu_consistency(self):
        topics = {
            "sensor_accel":   make_accel_df(rms=5.0),
            "sensor_accel_1": make_accel_df(rms=40.0),
        }
        result = run(topics)
        assert any(f.kind == "vibration.imu_mismatch" for f in result.findings)

    def test_only_in_flight_samples_count(self):
        df = make_accel_df(rms=45.0)
        df.loc[1000:, ["x", "y", "z"]] = make_accel_df(rms=5.0).loc[1000:, ["x", "y", "z"]].to_numpy()
        status = pd.DataFrame({"timestamp": [0, 1000 * 4000], "arming_state": [1, 2]})
        result = run({"sensor_accel": df, "vehicle_status": status})
        assert result.findings == []

    def test_missing_topic_skipped(self):
        assert not VibrationAnalyser().is_applicable(set())

    def test_confidence_in_range(self):
        result = run({"sensor_accel": make_accel_df(rms=70.0)})
        for f in result.findings:
            assert 0.0 <= f.confidence <= 1.0

    def test_category_is_vibration(self):
        result = run({"sensor_accel": make_accel_df(rms=50.0)})
        for f in result.findings:
            assert f.category == Category.VIBRATION
