"""
Tests for GPSAnalyser — fix quality, HDOP, jamming, spoofing, satellite count.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.gps import GPSAnalyser
from flightmd_core.models.findings import Severity, Category


def make_gps_df(
    n: int = 1000,
    fix_type: int = 3,
    satellites: int = 14,
    hdop: float = 0.9,
    jamming: int = 0,
    spoofing: int = 1,          # PX4 SPOOFING_STATE_NONE
) -> pd.DataFrame:
    ts = np.arange(n) * 200_000   # 5 Hz
    return pd.DataFrame({
        "timestamp":         ts,
        "fix_type":          np.full(n, fix_type, dtype=int),
        "satellites_used":   np.full(n, satellites, dtype=int),
        "hdop":              np.full(n, hdop),
        "jamming_indicator": np.full(n, jamming, dtype=int),
        "spoofing_state":    np.full(n, spoofing, dtype=int),
    })


def armed_between(t0_us, t1_us):
    return pd.DataFrame({"timestamp": [0, t0_us, t1_us], "arming_state": [1, 2, 1]})


def run(df, **extra):
    return GPSAnalyser().safe_analyse({"vehicle_gps_position": df, **extra}, {})


class TestGPSAnalyser:

    def test_healthy_gps_no_findings(self):
        result = run(make_gps_df())
        assert not result.skipped
        assert result.findings == []
        assert result.health_score == 100.0

    def test_no_fix_at_all_is_critical(self):
        result = run(make_gps_df(fix_type=1))
        critical = [f for f in result.findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        assert any("fix" in f.title.lower() for f in critical)

    def test_fix_lost_in_flight_is_critical(self):
        df = make_gps_df()
        df.loc[500:520, "fix_type"] = 1     # ~4 s outage after having a fix
        result = run(df)
        lost = [f for f in result.findings if f.kind == "gps.fix_lost"]
        assert len(lost) == 1
        assert lost[0].severity == Severity.CRITICAL
        assert lost[0].t_start_s == 100.0

    def test_brief_fix_dip_is_degradation_warning(self):
        df = make_gps_df()
        df.loc[500, "fix_type"] = 2         # one 0.2 s sample
        result = run(df)
        assert [f.kind for f in result.findings] == ["gps.fix_degraded"]
        assert result.findings[0].severity == Severity.WARNING

    def test_pre_fix_acquisition_is_not_fix_lost(self):
        """Logging starts before the receiver has a fix. That's the pad,
        not a fix lost during flight, and its HDOP of 99.99 isn't real."""
        df = make_gps_df()
        df.loc[:99, "fix_type"] = 0
        df.loc[:99, "hdop"] = 99.99
        df.loc[:99, "satellites_used"] = 0
        result = run(df)
        assert result.findings == []
        assert result.key_metrics["min_satellites"] == 14.0

    def test_pre_arm_and_post_disarm_ignored_with_arming_data(self):
        df = make_gps_df()
        df.loc[:99, "fix_type"] = 1
        df.loc[900:, "fix_type"] = 1
        status = armed_between(150 * 200_000, 850 * 200_000)
        result = run(df, vehicle_status=status)
        assert result.findings == []

    def test_hdop_warning(self):
        result = run(make_gps_df(hdop=2.5))
        hdop = [f for f in result.findings if f.kind == "gps.hdop"]
        assert len(hdop) == 1
        assert hdop[0].severity == Severity.WARNING

    def test_hdop_critical(self):
        result = run(make_gps_df(hdop=5.0))
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_single_hdop_spike_ignored(self):
        df = make_gps_df()
        df.loc[400, "hdop"] = 6.0
        result = run(df)
        assert result.findings == []

    def test_jamming_warning(self):
        result = run(make_gps_df(jamming=150))
        jam = [f for f in result.findings if f.kind == "gps.jamming"]
        assert len(jam) == 1
        assert jam[0].severity == Severity.WARNING

    def test_jamming_critical(self):
        result = run(make_gps_df(jamming=200))
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_single_jamming_spike_ignored(self):
        df = make_gps_df()
        df.loc[300, "jamming_indicator"] = 250
        result = run(df)
        assert result.findings == []

    def test_jamming_state_is_used(self):
        df = make_gps_df()
        df["jamming_state"] = 1
        df.loc[300:400, "jamming_state"] = 3    # PX4 JAMMING_STATE_CRITICAL
        result = run(df)
        jam = [f for f in result.findings if f.kind == "gps.jamming"]
        assert len(jam) == 1
        assert jam[0].severity == Severity.CRITICAL

    def test_spoofing_state_none_is_healthy(self):
        assert run(make_gps_df(spoofing=1)).findings == []
        assert run(make_gps_df(spoofing=0)).findings == []

    def test_spoofing_indicated_warning(self):
        """PX4 SPOOFING_STATE_INDICATED = 2."""
        result = run(make_gps_df(spoofing=2))
        spoof = [f for f in result.findings if "spoof" in f.title.lower()]
        assert len(spoof) == 1
        assert spoof[0].severity == Severity.WARNING

    def test_spoofing_multiple_critical(self):
        """PX4 SPOOFING_STATE_MULTIPLE = 3."""
        result = run(make_gps_df(spoofing=3))
        spoof = [f for f in result.findings if "spoof" in f.title.lower()]
        assert len(spoof) == 1
        assert spoof[0].severity == Severity.CRITICAL

    def test_satellite_drop_warning(self):
        df = make_gps_df(satellites=14)
        df.loc[200:225, "satellites_used"] = 8
        result = run(df)
        drop = [f for f in result.findings if f.kind == "gps.sat_drop"]
        assert len(drop) == 1

    def test_unknown_satellite_count_255_ignored(self):
        df = make_gps_df()
        df.loc[200:210, "satellites_used"] = 255
        result = run(df)
        assert result.findings == []

    def test_chart_data_populated(self):
        result = run(make_gps_df(jamming=200))
        assert result.findings
        for f in result.findings:
            assert "satellites" in f.chart_data
            assert "hdop" in f.chart_data
            assert len(f.chart_data["timestamps"]) == len(f.chart_data["hdop"])

    def test_nan_hdop_does_not_leak_into_chart(self):
        df = make_gps_df(jamming=200)
        df["hdop"] = df["hdop"].astype(float)
        df.loc[10:20, "hdop"] = np.nan
        result = run(df)
        for f in result.findings:
            assert all(v is None or np.isfinite(v) for v in f.chart_data["hdop"])

    def test_category_is_gps(self):
        result = run(make_gps_df(fix_type=1))
        for f in result.findings:
            assert f.category == Category.GPS

    def test_missing_topic_not_applicable(self):
        assert not GPSAnalyser().is_applicable(set())

    def test_health_score_penalised(self):
        assert run(make_gps_df(fix_type=1)).health_score < 100.0
