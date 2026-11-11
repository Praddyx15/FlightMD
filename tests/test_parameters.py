"""
Tests for ParameterAnalyser — firmware and recommended ranges, per-version
tables, dangerous combos, PX4 and ArduPilot.
"""

import numpy as np
import pytest

from flightmd_core.analysers.parameters import ParameterAnalyser, load_tables, pick_table
from flightmd_core.models.findings import Severity, Category
from flightmd_core.models.metadata import FlightMetadata


def run(params: dict, metadata=None):
    a = ParameterAnalyser()
    a.metadata = metadata
    return a.safe_analyse({}, params)


def px4(version):
    return FlightMetadata(duration_seconds=60.0, px4_version=version)


def copter(version="ArduCopter V4.7.1 (dbe79216)"):
    return FlightMetadata(duration_seconds=60.0, firmware_version=version, vehicle_type="Copter")


def table(autopilot, series, vehicle=None):
    return next(t for t in load_tables() if t["autopilot"] == autopilot
                and t["series"] == series and t["vehicle"] == vehicle)


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

    @pytest.mark.parametrize("series", [(1, 13), (1, 14), (1, 15)])
    def test_stock_defaults_produce_no_findings(self, series):
        """Every stock PX4 log used to get 7 'deprecated' INFO findings."""
        params = {k: float(e["default"]) for k, e in table("px4", series)["params"].items() if "default" in e}
        params.update({"SYS_AUTOSTART": 4001.0, "LND_FLIGHT_T_LO": 12345.0})
        assert run(params, px4("v%d.%d.0" % series)).findings == []
        assert run(params).findings == []

    def test_firmware_version_picks_the_table(self):
        """EKF2_DECL_TYPE's default 7 in 1.14 is above 1.15's maximum of 3."""
        assert run({"EKF2_DECL_TYPE": 7.0, "MAV_TYPE": 2}, px4("v1.14.3")).findings == []
        [f] = run({"EKF2_DECL_TYPE": 7.0, "MAV_TYPE": 2}, px4("v1.15.0")).findings
        assert f.kind == "params.above_range"
        assert "firmware's allowed maximum" in f.technical_summary
        assert "PX4 1.15" in f.technical_summary

    def test_unknown_version_uses_the_widest_range(self):
        assert run({"EKF2_DECL_TYPE": 7.0, "MAV_TYPE": 2}).findings == []

    @pytest.mark.parametrize("autopilot, vehicle, series, expected", [
        ("px4", None, (1, 14), "1.14"),
        ("px4", None, (1, 16), "1.15"),
        ("px4", None, (1, 12), "1.13"),
        ("ardupilot", "copter", (4, 6), "4.6"),
        ("ardupilot", "plane", (4, 8), "4.7"),
    ])
    def test_closest_table(self, autopilot, vehicle, series, expected):
        _, source = pick_table(autopilot, vehicle, series)
        assert source.endswith(f"{expected} metadata")

    def test_recommended_range_says_why(self):
        [f] = run({"MC_YAWRATE_P": 0.01, "MAV_TYPE": 2}, px4("v1.14.0")).findings
        assert "recommended minimum" in f.technical_summary
        assert "no feedback" in f.technical_summary
        assert f.param_changes[0].suggested_value == 0.2

    def test_reboot_required_is_mentioned(self):
        [f] = run({"IMU_DGYRO_CUTOFF": 2000.0, "MAV_TYPE": 2}, px4("v1.14.0")).findings
        assert "reboot" in f.recommendation.lower()
        assert f.param_changes[0].suggested_value == 30.0

    def test_range_finding_lists_its_param(self):
        [f] = run({"MC_ROLLRATE_P": 0.7}).findings
        assert f.params == ["MC_ROLLRATE_P"]

    @pytest.mark.parametrize("name", [
        "MC_ACRO_EXPO", "MC_ACRO_EXPO_Y", "MC_ACRO_SUPEXPO", "MC_ACRO_SUPEXPOY",
        "EKF2_MAG_DECL", "LND_FLIGHT_T_LO", "LND_FLIGHT_T_HI",
    ])
    def test_live_params_are_not_deprecated(self, name):
        assert run({name: 0.5, "SYS_AUTOSTART": 4001}).findings == []

    def test_live_param_is_not_called_deprecated(self):
        """MPC_VELD_LP is in PX4 1.13-1.15's metadata; it used to be flagged."""
        assert run({"MPC_VELD_LP": 5.0}).findings == []

    def test_float32_values_on_the_bound_are_in_range(self):
        """Autopilots store float32, so 0.05 arrives as 0.05000000074505806.
        On the bound is in range."""
        params = {name: float(np.float32(v)) for name, v in {
            "MC_ROLLRATE_P": 0.01, "MPC_THR_MIN": 0.4, "BAT_CRIT_THR": 0.25, "MC_ROLLRATE_D": 0.01,
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

    def test_ardupilot_params_are_assessed(self):
        result = run({"ATC_RAT_RLL_P": 0.135, "FRAME_CLASS": 1}, copter())
        assert not result.skipped
        assert result.findings == []

    def test_ardupilot_out_of_firmware_range(self):
        [f] = run({"ATC_RAT_RLL_P": 0.9, "FRAME_CLASS": 1}, copter()).findings
        assert f.kind == "params.above_range"
        assert "ArduCopter 4.7" in f.technical_summary
        rec = f.param_changes[0]
        # no defaults in ArduPilot's metadata, so the bound is suggested
        assert rec.suggested_value == 0.5
        assert rec.change_direction == "decrease"

    def test_ardupilot_without_version_still_checks(self):
        [f] = run({"ATC_RAT_RLL_P": 0.9, "FRAME_CLASS": 1}).findings
        assert f.kind == "params.above_range"

    def test_ardupilot_battery_failsafes_inverted(self):
        result = run({"BATT_LOW_VOLT": 10.5, "BATT_CRT_VOLT": 10.8, "FRAME_CLASS": 1}, copter())
        [f] = [f for f in result.findings if f.kind == "params.bat_thr_inverted"]
        assert f.severity == Severity.CRITICAL
        assert f.params == ["BATT_LOW_VOLT", "BATT_CRT_VOLT"]
        assert f.param_changes == []

    def test_ardupilot_disabled_failsafe_is_not_inverted(self):
        result = run({"BATT_LOW_VOLT": 0.0, "BATT_CRT_VOLT": 10.8, "FRAME_CLASS": 1}, copter())
        assert not any(f.kind == "params.bat_thr_inverted" for f in result.findings)

    def test_ardupilot_arming_checks_off(self):
        result = run({"ARMING_CHECK": 0.0, "FRAME_CLASS": 1}, copter("ArduCopter V4.6.3"))
        assert [f.kind for f in result.findings] == ["params.arming_checks_off"]

    def test_px4_combos_dont_run_on_ardupilot(self):
        result = run({"COM_RC_LOSS_T": 0.1, "FRAME_CLASS": 1, "ATC_RAT_RLL_P": 0.1}, copter())
        assert not any(f.kind == "params.rc_loss_short" for f in result.findings)

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
        assert combo.params == ["BAT_LOW_THR", "BAT_CRIT_THR"]

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
