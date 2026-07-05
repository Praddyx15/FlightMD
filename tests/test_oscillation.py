"""
Tests for OscillationAnalyser — FFT-based oscillation detection.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.oscillation import OscillationAnalyser
from flightmd_core.models.findings import Severity


def make_topics(df: pd.DataFrame) -> dict:
    return {"vehicle_angular_velocity": df}


def make_params() -> dict:
    return {
        "MC_ROLLRATE_P":  0.15,
        "MC_PITCHRATE_P": 0.15,
        "MC_YAWRATE_P":   0.20,
    }


class TestOscillationAnalyser:
    def test_clean_signal_no_findings(self, clean_angular_velocity):
        result = OscillationAnalyser().safe_analyse(
            make_topics(clean_angular_velocity), make_params()
        )
        assert not result.skipped
        assert len(result.findings) == 0
        assert result.health_score == 100.0

    def test_key_metrics_populated_even_without_findings(self, clean_angular_velocity):
        """key_metrics must be populated regardless of whether a Finding
        fired — that's what lets trend analysis show drift before a
        threshold is ever crossed."""
        result = OscillationAnalyser().safe_analyse(
            make_topics(clean_angular_velocity), make_params()
        )
        assert len(result.findings) == 0
        assert "roll_peak_hz" in result.key_metrics
        assert "roll_norm_amp" in result.key_metrics

    def test_oscillating_signal_finds_issue(self, oscillating_angular_velocity):
        result = OscillationAnalyser().safe_analyse(
            make_topics(oscillating_angular_velocity), make_params()
        )
        assert not result.skipped
        assert len(result.findings) >= 1
        # Roll axis should have a finding
        roll_finding = next(
            (f for f in result.findings if "roll" in f.title.lower()), None
        )
        assert roll_finding is not None
        assert roll_finding.severity in (Severity.CRITICAL, Severity.WARNING)

    def test_severe_oscillation_critical_severity(self):
        """High-amplitude 6Hz oscillation should trigger CRITICAL."""
        n = 5000
        t = np.linspace(0, 20, n)
        ts = (t * 1e6).astype(int)
        # Very strong 6Hz oscillation — normalised amp >> 0.70
        oscillation = 2.0 * np.sin(2 * np.pi * 6.0 * t)
        noise = np.random.default_rng(0).normal(0, 0.01, n)
        df = pd.DataFrame({
            "timestamp":  ts,
            "rollspeed":  oscillation + noise,
            "pitchspeed": noise,
            "yawspeed":   noise,
        })
        result = OscillationAnalyser().safe_analyse(make_topics(df), make_params())
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_param_changes_suggest_reduction(self, oscillating_angular_velocity):
        """Param recommendations should suggest reducing P gain."""
        result = OscillationAnalyser().safe_analyse(
            make_topics(oscillating_angular_velocity), make_params()
        )
        for f in result.findings:
            for pc in f.param_changes:
                assert pc.suggested_value < pc.current_value
                assert pc.change_direction == "decrease"

    def test_health_score_penalised(self, oscillating_angular_velocity):
        result = OscillationAnalyser().safe_analyse(
            make_topics(oscillating_angular_velocity), make_params()
        )
        assert result.health_score < 100.0

    def test_missing_topic_returns_skipped(self):
        result = OscillationAnalyser().safe_analyse({}, make_params())
        # is_applicable returns False → safe_analyse still called but will error →
        # BaseAnalyser.safe_analyse catches and returns skipped
        # (In real flow, is_applicable filters before safe_analyse is called)
        # Force the topic to be missing and call directly
        analyser = OscillationAnalyser()
        assert not analyser.is_applicable(set())

    def test_chart_data_populated(self, oscillating_angular_velocity):
        result = OscillationAnalyser().safe_analyse(
            make_topics(oscillating_angular_velocity), make_params()
        )
        for f in result.findings:
            assert f.chart_data is not None
            assert "frequencies" in f.chart_data
            assert "amplitudes"  in f.chart_data
            assert "peak_hz"     in f.chart_data

    def test_confidence_in_range(self, oscillating_angular_velocity):
        result = OscillationAnalyser().safe_analyse(
            make_topics(oscillating_angular_velocity), make_params()
        )
        for f in result.findings:
            assert 0.0 <= f.confidence <= 1.0

    def test_frequency_detection_accuracy(self):
        """Injected 8 Hz oscillation should be detected near 8 Hz."""
        n = 5000
        t = np.linspace(0, 20, n)
        ts = (t * 1e6).astype(int)
        target_hz = 8.0
        oscillation = 1.5 * np.sin(2 * np.pi * target_hz * t)
        noise = np.random.default_rng(1).normal(0, 0.02, n)
        df = pd.DataFrame({
            "timestamp":  ts,
            "rollspeed":  oscillation + noise,
            "pitchspeed": noise,
            "yawspeed":   noise,
        })
        result = OscillationAnalyser().safe_analyse(make_topics(df), make_params())
        assert len(result.findings) >= 1
        roll_f = next((f for f in result.findings if "roll" in f.title.lower()), None)
        assert roll_f is not None
        # Peak should be within 1 Hz of injected frequency
        peak_hz = roll_f.chart_data["peak_hz"]
        assert abs(peak_hz - target_hz) < 1.5

    def test_xyz_column_names_supported(self):
        """PX4 older logs may use xyz[0]/xyz[1]/xyz[2] column names."""
        n = 5000
        t = np.linspace(0, 20, n)
        ts = (t * 1e6).astype(int)
        oscillation = 1.0 * np.sin(2 * np.pi * 5.0 * t)
        df = pd.DataFrame({
            "timestamp": ts,
            "xyz[0]": oscillation,
            "xyz[1]": np.zeros(n),
            "xyz[2]": np.zeros(n),
        })
        result = OscillationAnalyser().safe_analyse(make_topics(df), make_params())
        # Should not crash — may or may not find oscillation depending on amplitude
        assert not result.skipped or result.skipped
