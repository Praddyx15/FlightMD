"""
Tests for ParameterAnalyser — safe ranges, dangerous combos, deprecated params.
"""

import json
import os

import numpy as np
import pytest

from flightmd_core.analysers.parameters import ParameterAnalyser, DATA_DIR
from flightmd_core.models.findings import Severity, Category


def run(params: dict):
    return ParameterAnalyser().safe_analyse({}, params)


def warn_or_worse(result):
    return [f for f in result.findings if f.severity in (Severity.CRITICAL, Severity.WARNING)]


class TestParameterAnalyser:

    def test_default_params_no_findings(self):
        params = {
            "MC_ROLLRATE_P":   0.15,
            "MC_PITCHRATE_P":  0.15,
            "MC_YAWRATE_P":    0.20,
            "MC_ROLLRATE_D":   0.003,
            "MC_PITCHRATE_D":  0.003,
            "MPC_XY_P":        0.95,
            "MPC_XY_VEL_P_ACC": 1.8,
            "BAT_LOW_THR":     0.15,
            "BAT_CRIT_THR":    0.07,
            "COM_RC_LOSS_T":   0.5,
        }
        result = run(params)
        assert not result.skipped
        assert warn_or_worse(result) == []

    def test_stock_v1_14_defaults_produce_no_findings(self):
        """Every stock PX4 log used to get 7 'deprecated' INFO findings."""
        with open(os.path.join(DATA_DIR, "px4_param_defaults", "v1_14.json"), encoding="utf-8") as f:
            params = {k: float(v) for k, v in json.load(f).items()}
        params.update({"LND_FLIGHT_T_LO": 12345.0, "LND_FLIGHT_T_HI": 0.0, "EKF2_MAG_DECL": 0.0})
        assert run(params).findings == []

    @pytest.mark.parametrize("name", [
        "MC_ACRO_EXPO", "MC_ACRO_EXPO_Y", "MC_ACRO_SUPEXPO", "MC_ACRO_SUPEXPOY",
        "EKF2_MAG_DECL", "LND_FLIGHT_T_LO", "LND_FLIGHT_T_HI",
    ])
    def test_live_params_are_not_deprecated(self, name):
        assert run({name: 0.5, "SYS_AUTOSTART": 4001}).findings == []

    def test_deprecated_param_info(self):
        result = run({"MPC_VELD_LP": 5.0})
        info = [f for f in result.findings if f.severity == Severity.INFO]
        assert len(info) == 1
        assert "deprecated" in info[0].title.lower()

    def test_float32_values_on_the_bound_are_in_range(self):
        """Autopilots store float32, so 0.05 arrives as 0.05000000074505806.
        On the bound is in range."""
        params = {name: float(np.float32(v)) for name, v in {
            "MC_ROLLRATE_P": 0.01, "MPC_THR_MIN": 0.4, "BAT_CRIT_THR": 0.3, "MC_ROLLRATE_D": 0.01,
        }.items()}
        assert run(params).findings == []

    def test_reported_values_are_not_float_noise(self):
        result = run({"MC_ROLLRATE_P": float(np.float32(0.7))})
        f = result.findings[0]
        assert "0.7" in f.technical_summary
        assert "0.699999" not in f.technical_summary
        assert f.param_changes[0].current_value == 0.7

    def test_param_above_safe_range_warning(self):
        result = run({"MC_ROLLRATE_P": 0.7})
        assert any(f.severity in (Severity.WARNING, Severity.CRITICAL) for f in result.findings)

    def test_param_below_safe_range_warning(self):
        result = run({"MC_ROLLRATE_P": 0.001})
        assert any("below" in f.title.lower() for f in result.findings)

    def test_negative_gain_with_zero_minimum_is_critical(self):
        """min == 0 used to make the severity maths negative, so a negative D
        gain never reached CRITICAL."""
        result = run({"MC_ROLLRATE_D": -0.002})
        assert [f.severity for f in result.findings] == [Severity.CRITICAL]

    def test_far_above_range_is_critical(self):
        result = run({"MC_ROLLRATE_D": 0.05})   # 5x the PX4 maximum
        assert [f.severity for f in result.findings] == [Severity.CRITICAL]

    def test_disarm_land_disabled_is_allowed(self):
        """COM_DISARM_LAND = -1 disables auto-disarm; PX4 allows it."""
        assert run({"COM_DISARM_LAND": -1.0}).findings == []

    def test_thr_min_zero_is_flagged(self):
        """MPC_THR_MIN = 0 lets the motors stop in flight."""
        result = run({"MPC_THR_MIN": 0.0})
        assert any("below" in f.title.lower() for f in result.findings)

    def test_suggested_value_is_firmware_default_not_range_edge(self):
        result = run({"MC_ROLLRATE_P": 0.001})
        rec = result.findings[0].param_changes[0]
        assert rec.suggested_value == 0.15

    def test_multicopter_ranges_skipped_on_fixed_wing(self):
        params = {"MAV_TYPE": 1, "MC_ROLLRATE_P": 0.9, "MPC_XY_P": 1.8, "MPC_XY_VEL_P_ACC": 1.2}
        assert run(params).findings == []

    def test_ardupilot_params_not_assessed(self):
        result = run({"ATC_RAT_RLL_P": 0.135, "FRAME_CLASS": 1})
        assert result.skipped

    def test_inverted_battery_thresholds_critical(self):
        result = run({"BAT_LOW_THR": 0.05, "BAT_CRIT_THR": 0.10})
        critical = [f for f in result.findings if f.severity == Severity.CRITICAL]
        assert any("battery" in f.title.lower() for f in critical)

    def test_combo_findings_carry_a_param_change(self):
        """Copy-All used to miss every dangerous-combination fix."""
        result = run({"BAT_LOW_THR": 0.05, "BAT_CRIT_THR": 0.10})
        combo = next(f for f in result.findings if f.kind == "params.bat_thr_inverted")
        assert len(combo.param_changes) == 1
        rec = combo.param_changes[0]
        assert rec.param_name == "BAT_LOW_THR"
        assert rec.suggested_value > 0.10
        assert "BAT_CRIT_THR=0.1" in combo.technical_summary

    def test_oscillation_risk_combo_warning(self):
        result = run({"MC_ROLLRATE_P": 0.35, "MC_ROLLRATE_D": 0.0005})
        combo = [f for f in result.findings if f.kind == "params.rate_p_high_d_low"]
        assert len(combo) == 1
        assert combo[0].severity == Severity.WARNING
        assert combo[0].param_changes[0].param_name == "MC_ROLLRATE_D"

    def test_short_rc_loss_timeout_warning(self):
        result = run({"COM_RC_LOSS_T": 0.1})
        assert any(f.kind == "params.rc_loss_short" for f in result.findings)

    def test_always_applicable(self):
        analyser = ParameterAnalyser()
        assert analyser.is_applicable(set())
        assert analyser.is_applicable({"some_random_topic"})

    def test_empty_params_skipped(self):
        assert run({}).skipped

    def test_category_is_parameters(self):
        for f in run({"MC_ROLLRATE_P": 0.8}).findings:
            assert f.category == Category.PARAMETERS

    def test_position_loop_instability_combo(self):
        result = run({"MPC_XY_P": 1.8, "MPC_XY_VEL_P_ACC": 1.2})
        assert any(f.kind == "params.pos_loop_risk" for f in result.findings)

    def test_health_score_penalised(self):
        assert run({"BAT_LOW_THR": 0.05, "BAT_CRIT_THR": 0.10}).health_score < 100.0

    def test_below_safe_range_emits_structured_param_change(self):
        result = run({"MC_ROLLRATE_P": 0.001})
        below = [f for f in result.findings if "below" in f.title.lower()]
        rec = below[0].param_changes
        assert len(rec) == 1
        assert rec[0].param_name == "MC_ROLLRATE_P"
        assert rec[0].current_value == 0.001
        assert rec[0].change_direction == "increase"
        assert rec[0].suggested_value > rec[0].current_value

    def test_above_safe_range_emits_structured_param_change(self):
        result = run({"MC_ROLLRATE_P": 0.7})
        above = [f for f in result.findings if "above" in f.title.lower()]
        rec = above[0].param_changes
        assert len(rec) == 1
        assert rec[0].param_name == "MC_ROLLRATE_P"
        assert rec[0].current_value == 0.7
        assert rec[0].change_direction == "decrease"
        assert rec[0].suggested_value < rec[0].current_value
