"""
Tests for BatteryAnalyser — voltage sag, capacity fade, temperature, C-rate.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.battery import BatteryAnalyser
from flightmd_core.models.findings import Severity, Category


def make_battery_df(
    n: int = 3000,
    idle_v: float = 16.8,
    loaded_v: float = 16.4,
    max_temp: float = 35.0,
    peak_current: float = 25.0,
) -> pd.DataFrame:
    """Idle at 2 A for 5 s, then a step to peak_current. The voltage step at
    t=5 s is idle_v - loaded_v, i.e. the pack's sag under that load."""
    t = np.linspace(0, 300, n)
    current = np.where(t < 5, 2.0, peak_current)
    voltage = np.where(
        current < 5,
        idle_v - t / 300 * 1.0,
        loaded_v - t / 300 * 0.8,
    )
    return pd.DataFrame({
        "timestamp":   (t * 1e6).astype(int),
        "voltage_v":   voltage + np.random.default_rng(0).normal(0, 0.02, n),
        "current_a":   current,
        "remaining":   np.clip(1.0 - t / 300 * 0.7, 0.1, 1.0),
        "temperature": np.full(n, max_temp),
    })


def make_discharge_df(r_pack: float = 0.015, n: int = 6000) -> pd.DataFrame:
    """10 min flight, current wandering 10-26 A, open-circuit voltage falling
    from 16.8 V to 12.8 V: a normal full discharge of a healthy 4S pack."""
    rng = np.random.default_rng(3)
    t = np.linspace(0, 600, n)
    current = np.where(t < 10, 1.0, 18 + 8 * np.sin(2 * np.pi * t / 23) + rng.normal(0, 1, n))
    ocv = 16.8 - 4.0 * t / 600
    return pd.DataFrame({
        "timestamp": (t * 1e6).astype(int),
        "voltage_v": ocv - r_pack * current + rng.normal(0, 0.02, n),
        "current_a": current,
    })


def run(df, params=None):
    return BatteryAnalyser().safe_analyse({"battery_status": df}, params or {})


class TestBatteryAnalyser:

    def test_healthy_battery_no_findings(self, healthy_battery):
        result = run(healthy_battery)
        assert not result.skipped
        assert len(result.findings) == 0

    def test_sag_per_cell_key_metric_populated_below_threshold(self, healthy_battery):
        """sag_per_cell_v must be there even when no finding fires; trends
        chart it to catch a pack degrading before it crosses a threshold."""
        result = run(healthy_battery)
        assert len(result.findings) == 0
        assert "sag_per_cell_v" in result.key_metrics

    def test_normal_discharge_is_not_sag(self):
        """A healthy pack going from 16.8 V to 12.8 V over a flight used to be
        reported as ~1 V/cell sag. Only the voltage response to current
        changes counts."""
        result = run(make_discharge_df(r_pack=0.015))
        assert not any(f.kind == "battery.sag" for f in result.findings)
        assert result.key_metrics["internal_resistance_mohm_per_cell"] < 6
        assert result.key_metrics["sag_per_cell_v"] < 0.2

    def test_high_internal_resistance_is_found_on_discharge(self):
        result = run(make_discharge_df(r_pack=0.12))
        sag = [f for f in result.findings if f.kind == "battery.sag"]
        assert len(sag) == 1

    def test_high_sag_warning(self):
        """2.4 V step on 4S at a 23 A load step = 0.6 V/cell."""
        result = run(make_battery_df(idle_v=16.8, loaded_v=14.4))
        sag = [f for f in result.findings if "sag" in f.title.lower()]
        assert len(sag) == 1
        assert sag[0].severity == Severity.WARNING

    def test_extreme_sag_critical(self):
        """4.8 V step on 4S = 1.2 V/cell."""
        result = run(make_battery_df(idle_v=16.8, loaded_v=12.0))
        assert any(f.severity == Severity.CRITICAL for f in result.findings)

    def test_temperature_warning(self):
        result = run(make_battery_df(max_temp=65.0))
        assert any("thermal" in f.title.lower() for f in result.findings)

    def test_hot_day_temperature_is_not_a_warning(self):
        """45-55 °C is a normal pack temperature in summer."""
        result = run(make_battery_df(max_temp=52.0))
        assert not any("thermal" in f.title.lower() for f in result.findings)

    def test_normal_temperature_no_thermal_finding(self):
        result = run(make_battery_df(max_temp=32.0))
        assert not any("thermal" in f.title.lower() for f in result.findings)

    def test_c_rate_uses_rated_capacity(self):
        """A short hop on a big pack: 40 A on 10 Ah is 4C. The old code
        divided by the mAh used in the flight and called it 100C."""
        t = np.linspace(0, 120, 1200)
        df = pd.DataFrame({
            "timestamp": (t * 1e6).astype(int),
            "voltage_v": np.full(len(t), 22.0),
            "current_a": np.where(t < 5, 1.0, 40.0),
            "capacity": 10000.0,
        })
        result = run(df)
        assert not any(f.kind == "battery.c_rate" for f in result.findings)
        assert result.key_metrics["peak_c_rate"] == 4.0

    def test_c_rate_warning_against_capacity_param(self):
        t = np.linspace(0, 120, 1200)
        df = pd.DataFrame({
            "timestamp": (t * 1e6).astype(int),
            "voltage_v": np.full(len(t), 16.0),
            "current_a": np.where(t < 5, 1.0, 50.0),
        })
        result = run(df, {"BAT1_CAPACITY": 1300.0})
        assert any(f.kind == "battery.c_rate" for f in result.findings)

    def test_no_c_rate_without_capacity(self):
        result = run(make_battery_df(peak_current=60.0))
        assert not any(f.kind == "battery.c_rate" for f in result.findings)
        assert "peak_c_rate" not in result.key_metrics

    def test_voltage_and_current_stay_row_aligned(self):
        """Gaps in one column must drop the whole row, not shift the other
        column against it (tlog voltage and current arrive separately)."""
        df = make_battery_df(n=1000)
        df.loc[::2, "current_a"] = np.nan
        result = run(df)
        assert not result.skipped
        assert result.key_metrics["consumed_mah"] > 0
        # chart timestamps still reach the end of the flight
        result2 = run(make_battery_df(n=1000, idle_v=16.8, loaded_v=12.0))
        chart = result2.findings[0].chart_data
        assert chart["timestamps"][-1] > 290_000

    def test_health_score_penalised(self):
        assert run(make_battery_df(idle_v=16.8, loaded_v=12.0)).health_score < 100.0

    def test_chart_data_present_on_findings(self):
        result = run(make_battery_df(idle_v=16.8, loaded_v=13.0))
        assert result.findings
        for f in result.findings:
            assert "voltage" in f.chart_data
            assert "current" in f.chart_data

    def test_missing_topic_skipped(self):
        assert not BatteryAnalyser().is_applicable(set())

    def test_category_is_battery(self):
        result = run(make_battery_df(idle_v=16.8, loaded_v=13.0))
        for f in result.findings:
            assert f.category == Category.BATTERY

    def test_cell_count_from_log_beats_voltage_guess(self):
        """6S Li-ion peaks at 25.2 V; 25.2/4.2 = 6 is right, but at 22.2 V
        (storage) the guess gives 5. A logged cell_count wins."""
        df = make_battery_df(idle_v=16.8, loaded_v=12.0)
        df["voltage_v"] = df["voltage_v"] * 22.2 / 16.8
        df["cell_count"] = 6
        result = run(df)
        sag = [f for f in result.findings if f.kind == "battery.sag"]
        assert len(sag) == 1
        assert sag[0].chart_data["n_cells"] == 6
        assert "6S" in sag[0].technical_summary

    def test_missing_voltage_column_skipped(self):
        df = pd.DataFrame({
            "timestamp": np.arange(100) * 1000,
            "current_a": np.full(100, 10.0),
        })
        assert run(df).skipped

    def test_capacity_fade_detected(self):
        """1000 mAh drawn while remaining fell 90% -> ~1111 mAh pack, rated 2000."""
        df = make_battery_df(n=1000, peak_current=12.0)
        df["current_a"] = 12.0          # 12 A for 300 s = 1000 mAh
        df["remaining"] = np.linspace(1.0, 0.1, len(df))
        df["capacity"] = 2000.0
        result = run(df)
        fade = [f for f in result.findings if "capacity fade" in f.title.lower()]
        assert len(fade) == 1
        assert fade[0].severity == Severity.WARNING

    def test_capacity_fade_not_computed_from_its_own_output(self):
        """When remaining is just 1 - drawn/capacity (PX4 with capacity set,
        ArduPilot), it can't reveal fade."""
        df = make_battery_df(n=1000)
        df["current_a"] = 12.0
        t_s = df["timestamp"].to_numpy() / 1e6
        drawn = 12.0 * t_s / 3.6
        df["capacity"] = 2000.0
        df["remaining"] = 1.0 - drawn / 2000.0
        result = run(df)
        assert not any(f.kind == "battery.capacity_fade" for f in result.findings)
