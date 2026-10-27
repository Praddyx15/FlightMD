"""
Tests for OscillationAnalyser — spectrogram-based oscillation detection.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.oscillation import OscillationAnalyser
from flightmd_core.models.findings import Severity


def make_topics(df: pd.DataFrame) -> dict:
    return {"vehicle_angular_velocity": df}


def make_params() -> dict:
    return {
        "MC_ROLLRATE_P":  0.15,
        "MC_PITCHRATE_P": 0.15,
        "MC_YAWRATE_P":   0.20,
        "MC_ROLLRATE_D":  0.003,
    }


def rates(seconds: float, fs: float = 250.0, seed: int = 0, noise: float = 0.02):
    t = np.arange(0, seconds, 1 / fs)
    rng = np.random.default_rng(seed)
    return t, pd.DataFrame({
        "timestamp":  (t * 1e6).astype(np.int64),
        "rollspeed":  rng.normal(0, noise, len(t)),
        "pitchspeed": rng.normal(0, noise, len(t)),
        "yawspeed":   rng.normal(0, noise, len(t)),
    })


def run(df, params=None):
    return OscillationAnalyser().safe_analyse(make_topics(df), make_params() if params is None else params)


class TestOscillationAnalyser:
    def test_clean_signal_no_findings(self, clean_angular_velocity):
        result = run(clean_angular_velocity)
        assert not result.skipped
        assert result.findings == []
        assert result.health_score == 100.0

    def test_key_metrics_populated_even_without_findings(self, clean_angular_velocity):
        result = run(clean_angular_velocity)
        assert result.findings == []
        assert "roll_peak_hz" in result.key_metrics
        assert "roll_norm_amp" in result.key_metrics

    def test_oscillating_signal_finds_issue(self, oscillating_angular_velocity):
        result = run(oscillating_angular_velocity)
        roll = next((f for f in result.findings if "roll" in f.title.lower()), None)
        assert roll is not None
        assert roll.severity in (Severity.CRITICAL, Severity.WARNING)

    def test_severe_oscillation_critical_severity(self):
        t, df = rates(20, noise=0.01)
        df["rollspeed"] += 2.0 * np.sin(2 * np.pi * 6.0 * t)
        result = run(df)
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_amplitude_estimate_in_deg_per_s(self):
        t, df = rates(20)
        df["rollspeed"] += 0.5 * np.sin(2 * np.pi * 7.0 * t)      # 28.6 deg/s
        result = run(df)
        assert abs(result.key_metrics["roll_osc_amp_dps"] - np.degrees(0.5)) < 3.0

    def test_param_changes_suggest_reduction(self, oscillating_angular_velocity):
        result = run(oscillating_angular_velocity)
        changes = [pc for f in result.findings for pc in f.param_changes]
        assert changes
        for pc in changes:
            assert pc.param_name == "MC_ROLLRATE_P"
            assert pc.suggested_value < pc.current_value
            assert pc.change_direction == "decrease"

    def test_recommendation_keeps_the_numbers(self, oscillating_angular_velocity):
        result = run(oscillating_angular_velocity)
        roll = next(f for f in result.findings if "roll" in f.title.lower())
        assert "MC_ROLLRATE_P" in roll.recommendation
        assert "0.15" in roll.recommendation

    def test_mid_band_oscillation_recommends_lower_d_not_higher(self):
        t, df = rates(20)
        df["rollspeed"] += 0.5 * np.sin(2 * np.pi * 22.0 * t)
        result = run(df)
        roll = next(f for f in result.findings if "roll" in f.title.lower())
        assert roll.kind == "oscillation.rate_d"
        assert [pc.param_name for pc in roll.param_changes] == ["MC_ROLLRATE_D"]
        assert roll.param_changes[0].change_direction == "decrease"

    def test_no_param_value_is_invented(self, oscillating_angular_velocity):
        """The old code filled current_value with a 0.15 default when the
        param wasn't in the log."""
        result = run(oscillating_angular_velocity, params={"MPC_XY_P": 0.95})
        assert result.findings
        assert all(f.param_changes == [] for f in result.findings)

    def test_fixed_wing_gets_fixed_wing_gains(self, oscillating_angular_velocity):
        params = {"MAV_TYPE": 1, "FW_RR_P": 0.05, "MC_ROLLRATE_P": 0.15}
        result = run(oscillating_angular_velocity, params=params)
        names = [pc.param_name for f in result.findings for pc in f.param_changes]
        assert names == ["FW_RR_P"]

    def test_ardupilot_copter_gets_atc_gains(self, oscillating_angular_velocity):
        params = {"FRAME_CLASS": 1, "ATC_RAT_RLL_P": 0.135}
        result = run(oscillating_angular_velocity, params=params)
        names = [pc.param_name for f in result.findings for pc in f.param_changes]
        assert names == ["ATC_RAT_RLL_P"]

    def test_rover_gets_no_rate_gain_advice(self, oscillating_angular_velocity):
        params = {"MAV_TYPE": 10, "MC_ROLLRATE_P": 0.15}
        result = run(oscillating_angular_velocity, params=params)
        assert result.findings
        assert all(f.param_changes == [] for f in result.findings)

    def test_short_burst_in_long_log_is_found(self):
        """A 20 s oscillation in a 20 min flight used to be averaged away."""
        t, df = rates(1200, noise=0.05)
        burst = (t > 600) & (t < 620)
        df.loc[burst, "rollspeed"] += 0.6 * np.sin(2 * np.pi * 8.0 * t[burst])
        result = run(df)
        roll = next((f for f in result.findings if "roll" in f.title.lower()), None)
        assert roll is not None
        assert roll.severity == Severity.WARNING
        assert 595 <= roll.t_start_s <= 605
        assert 615 <= roll.t_end_s <= 625

    def test_metric_does_not_grow_with_log_length(self):
        values = []
        for seconds in (30, 300):
            t, df = rates(seconds)
            df["rollspeed"] += 0.3 * np.sin(2 * np.pi * 6.0 * t)
            values.append(run(df).key_metrics["roll_osc_amp_dps"])
        assert abs(values[0] - values[1]) < 0.15 * values[0]

    def test_jittered_timestamps_still_give_right_frequency(self):
        t, df = rates(30)
        df["rollspeed"] += 0.8 * np.sin(2 * np.pi * 9.0 * t)
        jitter = np.random.default_rng(5).integers(-800, 800, len(df))
        df["timestamp"] = np.sort(df["timestamp"].to_numpy() + jitter)
        roll = next(f for f in run(df).findings if "roll" in f.title.lower())
        assert abs(roll.chart_data["peak_hz"] - 9.0) < 0.6

    def test_low_rate_telemetry_is_not_assessed(self):
        """tlog ATTITUDE at 4 Hz can't show a rate-loop oscillation."""
        t, df = rates(120, fs=4.0)
        result = run(df)
        assert result.skipped
        assert "Hz" in result.skip_reason

    def test_too_short_log_is_not_assessed(self):
        t, df = rates(0.5)
        result = run(df)
        assert result.skipped

    def test_health_score_penalised(self, oscillating_angular_velocity):
        assert run(oscillating_angular_velocity).health_score < 100.0

    def test_missing_topic_not_applicable(self):
        assert not OscillationAnalyser().is_applicable(set())

    def test_chart_data_populated(self, oscillating_angular_velocity):
        result = run(oscillating_angular_velocity)
        assert result.findings
        for f in result.findings:
            assert "frequencies" in f.chart_data
            assert "amplitudes" in f.chart_data
            assert "peak_hz" in f.chart_data
            assert len(f.chart_data["frequencies"]) == len(f.chart_data["amplitudes"])

    def test_chart_covers_the_peak(self, oscillating_angular_velocity):
        """The chart used to be the first 512 FFT bins, which for long logs
        stopped below 1 Hz."""
        result = run(oscillating_angular_velocity)
        chart = result.findings[0].chart_data
        assert chart["frequencies"][0] <= 1.0
        assert chart["frequencies"][-1] > chart["peak_hz"]

    def test_confidence_in_range(self, oscillating_angular_velocity):
        for f in run(oscillating_angular_velocity).findings:
            assert 0.0 <= f.confidence <= 1.0

    def test_frequency_detection_accuracy(self):
        t, df = rates(20, seed=1)
        df["rollspeed"] += 1.5 * np.sin(2 * np.pi * 8.0 * t)
        roll = next((f for f in run(df).findings if "roll" in f.title.lower()), None)
        assert roll is not None
        assert abs(roll.chart_data["peak_hz"] - 8.0) < 1.0

    def test_xyz_column_names_supported(self):
        t, df = rates(20)
        df = df.rename(columns={"rollspeed": "xyz[0]", "pitchspeed": "xyz[1]", "yawspeed": "xyz[2]"})
        df["xyz[0]"] += 1.0 * np.sin(2 * np.pi * 5.0 * t)
        result = run(df)
        assert any("roll" in f.title.lower() for f in result.findings)
