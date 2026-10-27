"""
Tests for MotorAnalyser — per-motor balance, dropouts, ESC slots, NaN handling.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.motors import MotorAnalyser
from flightmd_core.models.findings import Severity, Category


def make_esc_df(rpms=(5000, 5000, 5000, 5000), seconds=60.0, rate=10.0, slots=None,
                currents=None, seed=0) -> pd.DataFrame:
    """Hover at the given per-motor RPM, with 2% noise. `slots` adds empty
    PX4-style esc[] slots up to that count; esc_count stays the real number."""
    n = int(seconds * rate)
    rng = np.random.default_rng(seed)
    data = {"timestamp": (np.arange(n) * 1e6 / rate).astype(np.int64)}
    for i, r in enumerate(rpms):
        data[f"esc[{i}].esc_rpm"] = r * (1 + rng.normal(0, 0.02, n))
        if currents is not None:
            data[f"esc[{i}].esc_current"] = currents[i] * (1 + rng.normal(0, 0.02, n))
    for i in range(len(rpms), slots or 0):
        data[f"esc[{i}].esc_rpm"] = np.zeros(n)
        data[f"esc[{i}].esc_current"] = np.zeros(n)
    data["esc_count"] = np.full(n, len(rpms))
    return pd.DataFrame(data)


def run(df, **extra):
    return MotorAnalyser().safe_analyse({"esc_status": df, **extra}, {})


class TestMotorAnalyser:

    def test_balanced_quad_no_findings(self):
        result = run(make_esc_df())
        assert not result.skipped
        assert result.findings == []
        assert result.key_metrics["motor_balance_index"] < 0.02

    def test_px4_eight_slots_with_four_motors(self):
        """PX4 logs 8 esc[] slots; the 4 empty ones used to halve the mean
        current and block hover detection."""
        df = make_esc_df(slots=8, currents=(10, 10, 10, 10))
        result = run(df)
        assert result.findings == []
        assert "motor_balance_index" in result.key_metrics
        assert "motor_5_rpm_dev_pct" not in result.key_metrics

    def test_weak_motor_is_named(self):
        result = run(make_esc_df(rpms=(5000, 5000, 5000, 6400)))
        imb = [f for f in result.findings if f.kind == "motors.rpm_imbalance"]
        assert len(imb) == 1
        assert "Motor 4" in imb[0].title
        per_motor = imb[0].chart_data["per_motor"]
        assert [m["motor"] for m in per_motor] == [1, 2, 3, 4]
        assert per_motor[3]["deviation_pct"] > 15
        assert result.key_metrics["motor_4_rpm_dev_pct"] > 15

    def test_critical_imbalance_is_reachable(self):
        """Hover used to be selected with RPM spread < 0.15, so a spread
        above 0.15 could never be measured."""
        result = run(make_esc_df(rpms=(4000, 4000, 4000, 7000)))
        assert any(f.severity == Severity.CRITICAL and f.kind == "motors.rpm_imbalance"
                   for f in result.findings)

    def test_current_imbalance_at_hover(self):
        df = make_esc_df(currents=(10, 10, 10, 14))
        result = run(df)
        cur = [f for f in result.findings if f.kind == "motors.current_imbalance"]
        assert len(cur) == 1
        assert "Motor 4" in cur[0].title

    def test_missing_telemetry_is_not_a_dropout(self):
        """ArduPilot ESC rows from different instances don't line up;
        NaN means 'no sample', not 'motor stopped'."""
        df = make_esc_df()
        df.loc[df.index % 3 == 0, "esc[2].esc_rpm"] = np.nan
        result = run(df)
        assert not any(f.kind == "motors.dropout" for f in result.findings)

    def test_real_dropout_detected(self):
        df = make_esc_df()
        df.loc[300:305, "esc[1].esc_rpm"] = 0.0     # 0.6 s at 10 Hz
        result = run(df)
        drop = [f for f in result.findings if f.kind == "motors.dropout"]
        assert len(drop) == 1
        assert drop[0].severity == Severity.CRITICAL
        assert "Motor 2" in drop[0].title
        assert drop[0].t_start_s == 30.0

    def test_spin_down_after_landing_is_not_a_dropout(self):
        df = make_esc_df()
        for i in range(4):
            df.loc[500:, f"esc[{i}].esc_rpm"] = 0.0
        result = run(df)
        assert not any(f.kind == "motors.dropout" for f in result.findings)

    def test_spin_down_after_disarm_ignored_with_arming_data(self):
        df = make_esc_df()
        df.loc[500:, "esc[0].esc_rpm"] = 0.0        # one motor stops first after disarm
        status = pd.DataFrame({"timestamp": [0, 1_000_000, 49_000_000], "arming_state": [1, 2, 1]})
        result = run(df, vehicle_status=status)
        assert not any(f.kind == "motors.dropout" for f in result.findings)

    def test_esc_thermal(self):
        df = make_esc_df()
        df["esc[0].esc_temperature"] = np.linspace(40, 95, len(df))
        df["esc[1].esc_temperature"] = 50.0
        result = run(df)
        hot = [f for f in result.findings if f.kind == "motors.esc_thermal"]
        assert len(hot) == 1
        assert "Motor 1" in hot[0].title

    def test_no_rpm_columns_skipped(self):
        df = pd.DataFrame({"timestamp": np.arange(10), "esc_count": 4})
        assert run(df).skipped

    def test_columns_ordered_numerically(self):
        rpms = [5000] * 10 + [7000, 5000]
        result = run(make_esc_df(rpms=tuple(rpms)))
        imb = [f for f in result.findings if f.kind == "motors.rpm_imbalance"]
        assert imb and "Motor 11" in imb[0].title

    def test_chart_has_no_nan(self):
        df = make_esc_df(rpms=(5000, 5000, 5000, 6400))
        df.loc[::4, "esc[0].esc_rpm"] = np.nan
        result = run(df)
        for f in result.findings:
            for series in f.chart_data["rpm_per_motor"].values():
                assert all(v is None or np.isfinite(v) for v in series)

    def test_category_is_motors(self):
        for f in run(make_esc_df(rpms=(5000, 5000, 5000, 6400))).findings:
            assert f.category == Category.MOTORS
