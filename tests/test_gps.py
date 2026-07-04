"""
Tests for GPSAnalyser — fix quality, HDOP, jamming, spoofing, satellite count.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.gps import GPSAnalyser
from flightmd_core.models.findings import Severity, Category


def make_gps_df(
    n: int = 1000,
    fix_type: int = 3,
    satellites: int = 14,
    hdop: float = 0.9,
    jamming: int = 0,
    spoofing: int = 2,
) -> pd.DataFrame:
    ts = np.arange(n) * 200_000   # 200ms steps → 5 Hz
    return pd.DataFrame({
        "timestamp":        ts,
        "fix_type":         np.full(n, fix_type, dtype=int),
        "satellites_used":  np.full(n, satellites, dtype=int),
        "hdop":             np.full(n, hdop),
        "jamming_indicator": np.full(n, jamming, dtype=int),
        "spoofing_state":   np.full(n, spoofing, dtype=int),
    })


class TestGPSAnalyser:

    def test_healthy_gps_no_findings(self, healthy_gps):
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": healthy_gps}, {})
        assert not result.skipped
        assert len(result.findings) == 0
        assert result.health_score == 100.0

    def test_fix_loss_critical(self):
        """fix_type < 3 sustained → CRITICAL."""
        df = make_gps_df(fix_type=1)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        critical = [f for f in result.findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        assert any("fix" in f.title.lower() for f in critical)

    def test_hdop_warning(self):
        """HDOP > 2.0 → WARNING."""
        df = make_gps_df(hdop=2.5)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        hdop_findings = [f for f in result.findings if "hdop" in f.title.lower() or "uncertainty" in f.title.lower()]
        assert len(hdop_findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_hdop_critical(self):
        """HDOP > 4.0 → CRITICAL."""
        df = make_gps_df(hdop=5.0)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_jamming_warning(self):
        """jamming_indicator > 100 → WARNING."""
        df = make_gps_df(jamming=150)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        jam_findings = [f for f in result.findings if "jam" in f.title.lower() or "interference" in f.title.lower()]
        assert len(jam_findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_jamming_critical(self):
        """jamming_indicator > 180 → CRITICAL."""
        df = make_gps_df(jamming=200)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_spoofing_indeterminate_warning(self):
        """spoofing_state = 3 → WARNING."""
        df = make_gps_df(spoofing=3)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        spoof_findings = [f for f in result.findings if "spoof" in f.title.lower()]
        assert len(spoof_findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_spoofing_detected_critical(self):
        """spoofing_state = 4 → CRITICAL."""
        df = make_gps_df(spoofing=4)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_satellite_drop_warning(self):
        """Drop of >= 4 satellites in 5s → WARNING."""
        df = make_gps_df(satellites=14)
        # Inject a drop: 5 Hz × 5s = 25 samples
        df.loc[200:225, "satellites_used"] = 8   # drop of 6
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        drop_findings = [f for f in result.findings if "satellite" in f.title.lower() or "drop" in f.title.lower()]
        assert len(drop_findings) >= 1

    def test_chart_data_populated(self):
        df = make_gps_df(jamming=200)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        for f in result.findings:
            if f.chart_data:
                assert "satellites" in f.chart_data
                assert "hdop" in f.chart_data

    def test_category_is_gps(self):
        df = make_gps_df(fix_type=1)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        for f in result.findings:
            assert f.category == Category.GPS

    def test_missing_topic_not_applicable(self):
        analyser = GPSAnalyser()
        assert not analyser.is_applicable(set())

    def test_health_score_penalised(self):
        df = make_gps_df(fix_type=1)
        result = GPSAnalyser().safe_analyse({"vehicle_gps_position": df}, {})
        assert result.health_score < 100.0
