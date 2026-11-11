"""
Tests for VibrationAnalyser — high-passed RMS, clipping, multi-IMU.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.vibration import VibrationAnalyser, counter_increase
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


def imu_status(metric: float, n: int = 600, **cols) -> pd.DataFrame:
    """vehicle_imu_status at 10 Hz."""
    df = pd.DataFrame({
        "timestamp": np.arange(n) * 100_000,
        "accel_vibration_metric": np.full(n, metric),
        "gyro_vibration_metric": np.full(n, 0.02),
        "accel_clipping[0]": np.zeros(n),
        "accel_clipping[1]": np.zeros(n),
        "accel_clipping[2]": np.zeros(n),
        "accel_error_count": np.zeros(n),
    })
    for k, v in cols.items():
        df[k] = v
    return df


def vibe(level: float, n: int = 600, **cols) -> pd.DataFrame:
    """ArduPilot VIBE / MAVLink VIBRATION at 10 Hz."""
    df = pd.DataFrame({
        "timestamp": np.arange(n) * 100_000,
        "vibration_x": np.full(n, level * 0.8),
        "vibration_y": np.full(n, level * 0.9),
        "vibration_z": np.full(n, level),
    })
    for k, v in cols.items():
        df[k] = v
    return df


ARDU = {"FRAME_CLASS": 1.0, "ATC_RAT_RLL_P": 0.135}
PX4 = {"MAV_TYPE": 2.0, "MC_ROLLRATE_P": 0.15}


class TestAutopilotMetrics:

    @pytest.mark.parametrize("metric, kind", [
        (3.0, None),
        (7.0, "vibration.elevated"),
        (12.0, "vibration.critical"),
    ])
    def test_px4_metric_uses_flight_review_bands(self, metric, kind):
        result = run({"vehicle_imu_status": imu_status(metric)})
        kinds = [f.kind for f in result.findings]
        assert kinds == ([kind] if kind else [])
        assert result.key_metrics["max_accel_vibration_metric"] == metric
        assert "max_imu_rms" not in result.key_metrics

    def test_px4_metric_wins_over_raw_accel(self):
        topics = {"vehicle_imu_status": imu_status(2.0), "sensor_accel": make_accel_df(rms=45.0)}
        assert run(topics).findings == []

    def test_short_spike_is_not_a_level(self):
        m = np.full(600, 2.0)
        m[100:120] = 15.0     # 2 s of 60 s, under the 95th percentile
        result = run({"vehicle_imu_status": imu_status(0.0, **{"accel_vibration_metric": m})})
        assert not any(f.kind.startswith("vibration.") and f.kind != "vibration.clipping"
                       for f in result.findings)

    def test_px4_clipping_counter_counts_only_in_flight(self):
        clips = np.zeros(600)
        clips[50:] = 500        # clipped on the ground before arming
        clips[300:] += 150      # and 150 more in flight
        status = pd.DataFrame({"timestamp": [0, 20_000_000], "arming_state": [1, 2]})
        topics = {"vehicle_imu_status": imu_status(2.0, **{"accel_clipping[2]": clips}),
                  "vehicle_status": status}
        result = run(topics)
        [clip] = [f for f in result.findings if f.kind == "vibration.clipping"]
        assert clip.severity == Severity.WARNING
        assert result.key_metrics["total_clip_count"] == 150.0

    def test_px4_imu_errors(self):
        errors = np.concatenate([np.zeros(300), np.full(300, 25.0)])
        result = run({"vehicle_imu_status": imu_status(2.0, accel_error_count=errors)})
        assert [f.kind for f in result.findings] == ["vibration.imu_errors"]
        assert result.findings[0].severity == Severity.INFO

    @pytest.mark.parametrize("level, kind", [
        (20.0, None),
        (35.0, "vibration.elevated"),
        (70.0, "vibration.critical"),
    ])
    def test_ardupilot_vibe_uses_30_60(self, level, kind):
        result = VibrationAnalyser().safe_analyse({"vibration": vibe(level)}, ARDU)
        assert [f.kind for f in result.findings] == ([kind] if kind else [])
        assert result.key_metrics["max_imu_rms"] == level

    def test_ardupilot_low_clip_count_is_info(self):
        """ArduPilot: low numbers (<100) are likely ok, e.g. a hard landing."""
        clips = np.linspace(0, 50, 600).round()
        result = VibrationAnalyser().safe_analyse({"vibration": vibe(10.0, clipping_0=clips)}, ARDU)
        [clip] = [f for f in result.findings if f.kind == "vibration.clipping"]
        assert clip.severity == Severity.INFO

    def test_ardupilot_per_imu_clipping_is_not_double_counted(self):
        clips = np.linspace(0, 200, 600).round()
        topics = {
            "vibration": vibe(10.0, clipping_0=np.zeros(600)),
            "vibration_1": vibe(10.0, clipping_1=clips),
        }
        result = VibrationAnalyser().safe_analyse(topics, ARDU)
        clip = [f for f in result.findings if f.kind == "vibration.clipping"]
        assert len(clip) == 1
        assert "IMU 1" in clip[0].title
        assert clip[0].severity == Severity.WARNING
        assert result.key_metrics["total_clip_count"] == 200.0

    def test_counter_restart_is_not_negative(self):
        clips = np.array([0, 10, 20, 0, 5], dtype=float)
        assert counter_increase(clips, np.ones(5, dtype=bool)) == 25

    def test_px4_tlog_vibration_reads_z_only(self):
        """PX4 puts the coning and gyro metrics in vibration_x/y."""
        df = vibe(0.0, vibration_x=np.full(600, 50.0), vibration_y=np.full(600, 0.5),
                  vibration_z=np.full(600, 6.0))
        result = VibrationAnalyser().safe_analyse({"vibration": df}, PX4)
        assert [f.kind for f in result.findings] == ["vibration.elevated"]
        assert result.key_metrics["max_accel_vibration_metric"] == 6.0

        df["vibration_z"] = 3.0
        assert VibrationAnalyser().safe_analyse({"vibration": df}, PX4).findings == []

    def test_imu_mismatch_scales_with_the_metric(self):
        topics = {"vehicle_imu_status": imu_status(1.0), "vehicle_imu_status_1": imu_status(4.5)}
        result = run(topics)
        assert [f.kind for f in result.findings] == ["vibration.imu_mismatch"]
