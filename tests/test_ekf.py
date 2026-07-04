"""
Tests for EKFAnalyser — innovation flags, solution validity, wind anomalies.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.ekf import EKFAnalyser
from flightmd_core.models.findings import Severity, Category


def make_healthy_estimator_status(n: int = 1000) -> pd.DataFrame:
    ts = np.arange(n) * 20_000   # 20ms steps → 50 Hz
    return pd.DataFrame({
        "timestamp":              ts,
        "innovation_check_flags": np.zeros(n, dtype=int),
        "solution_status_flags":  np.full(n, 0b111111, dtype=int),
        "wind_vel_n":             np.full(n, 2.0),
        "wind_vel_e":             np.full(n, 1.0),
    })


def make_flagged_estimator_status(flag_bit: int, n: int = 1000, start: int = 100) -> pd.DataFrame:
    df = make_healthy_estimator_status(n)
    df.loc[start:start + 200, "innovation_check_flags"] = (1 << flag_bit)
    return df


class TestEKFAnalyser:

    def test_healthy_log_no_findings(self):
        df = make_healthy_estimator_status()
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        assert not result.skipped
        assert len(result.findings) == 0
        assert result.health_score == 100.0

    def test_sustained_innovation_flag_raises_warning(self):
        """200 samples flagged at 50 Hz = 4s — above 0.5s threshold → WARNING."""
        df = make_flagged_estimator_status(flag_bit=8)  # heading innovation
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        assert len(result.findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_brief_innovation_flag_is_info(self):
        """Very few samples flagged → INFO severity."""
        df = make_healthy_estimator_status()
        # Only 5 samples flagged (0.1s at 50Hz) → brief spike
        df.loc[100:104, "innovation_check_flags"] = (1 << 3)
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        info_findings = [f for f in result.findings if f.severity == Severity.INFO]
        assert len(info_findings) >= 1

    def test_solution_flag_invalid_raises_warning(self):
        """Horizontal velocity invalid for significant period → WARNING."""
        df = make_healthy_estimator_status()
        # Clear bit 1 (horizontal velocity valid) for 30% of samples
        n_invalid = 300
        flags = df["solution_status_flags"].values.copy()
        flags[:n_invalid] = flags[:n_invalid] & ~(1 << 1)
        df["solution_status_flags"] = flags
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_wind_jump_detected(self):
        """Sudden wind speed change > 5 m/s → WARNING."""
        df = make_healthy_estimator_status()
        df.loc[500, "wind_vel_n"] = 12.0  # sudden jump
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        wind_findings = [
            f for f in result.findings
            if "wind" in f.title.lower()
        ]
        assert len(wind_findings) >= 1

    def test_missing_topic_skipped(self):
        analyser = EKFAnalyser()
        assert not analyser.is_applicable(set())

    def test_category_is_ekf(self):
        df = make_flagged_estimator_status(flag_bit=5)
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        for f in result.findings:
            assert f.category == Category.EKF

    def test_health_score_decreases_on_findings(self):
        df = make_flagged_estimator_status(flag_bit=8)
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        if result.findings:
            assert result.health_score < 100.0

    def test_innovation_ratios_topic_used(self):
        """estimator_innovation_test_ratios topic triggers ratio analysis."""
        est_df = make_healthy_estimator_status()
        n = 1000
        ts = np.arange(n) * 20_000
        # Column exceeds 1.0 for 50 samples (1s) → WARNING
        ratio_df = pd.DataFrame({
            "timestamp":     ts,
            "vel_pos_innov_ratio": np.where(
                (np.arange(n) >= 200) & (np.arange(n) < 250), 1.5, 0.2
            ),
        })
        topics = {
            "estimator_status": est_df,
            "estimator_innovation_test_ratios": ratio_df,
        }
        result = EKFAnalyser().safe_analyse(topics, {})
        ratio_findings = [
            f for f in result.findings
            if "ratio" in f.title.lower() or "innovation" in f.title.lower()
        ]
        assert len(ratio_findings) >= 1

    def test_confidence_bounded(self):
        df = make_flagged_estimator_status(flag_bit=3)
        result = EKFAnalyser().safe_analyse({"estimator_status": df}, {})
        for f in result.findings:
            assert 0.0 <= f.confidence <= 1.0
