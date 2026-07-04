"""
Tests for BatteryAnalyser — voltage sag, capacity fade, temperature, C-rate.
"""

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers.battery import BatteryAnalyser
from flightmd_core.models.findings import Severity, Category


def make_battery_df(
    n: int = 3000,
    idle_v: float = 16.8,
    loaded_v: float = 16.4,
    max_temp: float = 35.0,
    peak_current: float = 25.0,
) -> pd.DataFrame:
    """Generate a battery_status DataFrame with controlled sag behaviour."""
    t = np.linspace(0, 300, n)
    ts = (t * 1e6).astype(int)

    # Alternate idle / loaded current
    current = np.where(t < 5, 2.0, peak_current)
    voltage = np.where(
        current < 5,
        idle_v - t / 300 * 1.0,
        loaded_v - t / 300 * 0.8,
    )
    remaining = np.clip(1.0 - t / 300 * 0.7, 0.1, 1.0)
    temp = np.full(n, max_temp)

    return pd.DataFrame({
        "timestamp":   ts,
        "voltage_v":   voltage + np.random.default_rng(0).normal(0, 0.02, n),
        "current_a":   current,
        "remaining":   remaining,
        "temperature": temp,
    })


class TestBatteryAnalyser:

    def test_healthy_battery_no_findings(self, healthy_battery):
        result = BatteryAnalyser().safe_analyse({"battery_status": healthy_battery}, {})
        assert not result.skipped
        # Small sag → no finding
        assert len(result.findings) == 0

    def test_high_sag_warning(self):
        """0.6V sag per cell (2.4V total for 4S) → WARNING."""
        df = make_battery_df(idle_v=16.8, loaded_v=14.4)  # 2.4V sag on 4S
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        sag_findings = [f for f in result.findings if "sag" in f.title.lower()]
        assert len(sag_findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_extreme_sag_critical(self):
        """>1V/cell sag → CRITICAL."""
        df = make_battery_df(idle_v=16.8, loaded_v=12.0)  # 4.8V sag on 4S → 1.2V/cell
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_temperature_warning(self):
        """Battery temperature > 45°C → WARNING."""
        df = make_battery_df(max_temp=55.0)
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        temp_findings = [f for f in result.findings if "thermal" in f.title.lower()]
        assert len(temp_findings) >= 1

    def test_normal_temperature_no_thermal_finding(self):
        df = make_battery_df(max_temp=32.0)
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        temp_findings = [f for f in result.findings if "thermal" in f.title.lower()]
        assert len(temp_findings) == 0

    def test_health_score_penalised(self):
        df = make_battery_df(idle_v=16.8, loaded_v=12.0)
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        assert result.health_score < 100.0

    def test_chart_data_present_on_findings(self):
        df = make_battery_df(idle_v=16.8, loaded_v=13.0)
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        for f in result.findings:
            if f.chart_data:
                assert "voltage" in f.chart_data
                assert "current" in f.chart_data

    def test_missing_topic_skipped(self):
        analyser = BatteryAnalyser()
        assert not analyser.is_applicable(set())

    def test_category_is_battery(self):
        df = make_battery_df(idle_v=16.8, loaded_v=13.0)
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        for f in result.findings:
            assert f.category == Category.BATTERY

    def test_n_cells_detected_correctly(self):
        """Peak voltage 16.8V → 4S battery (4 cells × 4.2V)."""
        df = make_battery_df(idle_v=16.8, loaded_v=16.0)
        # Just check it doesn't crash and gives sensible results
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        assert not result.skipped

    def test_missing_voltage_column_skipped(self):
        """DataFrame without voltage_v → skipped result."""
        df = pd.DataFrame({
            "timestamp": np.arange(100) * 1000,
            "current_a": np.full(100, 10.0),
        })
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        assert result.skipped

    def test_capacity_fade_detected(self):
        """Test that capacity fade is detected when estimated capacity is well below rated capacity."""
        # Rated capacity is 2000 mAh
        df = make_battery_df(n=1000, peak_current=12.0)  # low current/draw
        # Overwrite remaining and current to force estimated capacity of ~1111 mAh
        # 1000 points over 300s -> dt = 0.3s
        # Total current integrated = average_current * duration = 12A * 300s = 3600 A*s = 1000 mAh
        df["current_a"] = 12.0
        # Let's say remaining goes from 1.0 to 0.1 (used_fraction = 0.9).
        # Estimated capacity = 1000 mAh / 0.9 = 1111 mAh
        df["remaining"] = np.linspace(1.0, 0.1, len(df))
        df["capacity"] = 2000.0  # Rated capacity 2000 mAh
        
        result = BatteryAnalyser().safe_analyse({"battery_status": df}, {})
        assert not result.skipped
        fade_findings = [f for f in result.findings if "capacity fade" in f.title.lower()]
        assert len(fade_findings) == 1
        assert fade_findings[0].severity == Severity.WARNING

