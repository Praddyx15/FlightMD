"""
Tests for ParameterAnalyser — safe ranges, dangerous combos, deprecated params.
"""

import pytest
from flightmd_core.analysers.parameters import ParameterAnalyser
from flightmd_core.models.findings import Severity, Category


def run(params: dict) -> object:
    return ParameterAnalyser().safe_analyse({}, params)


class TestParameterAnalyser:

    def test_default_params_no_findings(self):
        """All-default parameters → no findings (except possibly info)."""
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
        critical_warn = [f for f in result.findings if f.severity in (Severity.CRITICAL, Severity.WARNING)]
        assert len(critical_warn) == 0

    def test_param_above_safe_range_warning(self):
        """MC_ROLLRATE_P = 0.7 exceeds max of 0.6 → WARNING or CRITICAL."""
        result = run({"MC_ROLLRATE_P": 0.7})
        assert len(result.findings) >= 1
        assert any(f.severity in (Severity.WARNING, Severity.CRITICAL) for f in result.findings)

    def test_param_below_safe_range_warning(self):
        """MC_ROLLRATE_P = 0.001 below min of 0.01 → WARNING or CRITICAL."""
        result = run({"MC_ROLLRATE_P": 0.001})
        assert len(result.findings) >= 1
        above_threshold = [f for f in result.findings if "below" in f.title.lower()]
        assert len(above_threshold) >= 1

    def test_inverted_battery_thresholds_critical(self):
        """BAT_LOW_THR < BAT_CRIT_THR → CRITICAL dangerous combination."""
        result = run({"BAT_LOW_THR": 0.05, "BAT_CRIT_THR": 0.10})
        critical = [f for f in result.findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        assert any("battery" in f.title.lower() or "threshold" in f.title.lower() for f in critical)

    def test_oscillation_risk_combo_warning(self):
        """MC_ROLLRATE_P > 0.3 and MC_ROLLRATE_D < 0.001 → WARNING combo."""
        result = run({"MC_ROLLRATE_P": 0.35, "MC_ROLLRATE_D": 0.0005})
        combo_findings = [
            f for f in result.findings
            if "oscillation" in f.title.lower() or "rate p" in f.title.lower()
        ]
        assert len(combo_findings) >= 1
        assert any(f.severity == Severity.WARNING for f in result.findings)

    def test_short_rc_loss_timeout_warning(self):
        """COM_RC_LOSS_T < 0.5 → WARNING."""
        result = run({"COM_RC_LOSS_T": 0.1})
        rc_findings = [f for f in result.findings if "rc" in f.title.lower() or "loss" in f.title.lower()]
        assert len(rc_findings) >= 1

    def test_deprecated_param_info(self):
        """Deprecated parameter → INFO finding."""
        result = run({"MC_ACRO_EXPO": 0.69})
        info_findings = [f for f in result.findings if f.severity == Severity.INFO]
        assert len(info_findings) >= 1
        assert any("deprecated" in f.title.lower() for f in info_findings)

    def test_always_applicable(self):
        """ParameterAnalyser overrides is_applicable → always True."""
        analyser = ParameterAnalyser()
        assert analyser.is_applicable(set())
        assert analyser.is_applicable({"some_random_topic"})

    def test_empty_params_skipped(self):
        result = run({})
        assert result.skipped

    def test_category_is_parameters(self):
        result = run({"MC_ROLLRATE_P": 0.8})
        for f in result.findings:
            assert f.category == Category.PARAMETERS

    def test_position_loop_instability_combo(self):
        """MPC_XY_P > 1.5 and MPC_XY_VEL_P_ACC < 1.5 → WARNING."""
        result = run({"MPC_XY_P": 1.8, "MPC_XY_VEL_P_ACC": 1.2})
        combo_findings = [
            f for f in result.findings
            if "position" in f.title.lower() or "instability" in f.title.lower()
        ]
        assert len(combo_findings) >= 1

    def test_health_score_penalised(self):
        result = run({"BAT_LOW_THR": 0.05, "BAT_CRIT_THR": 0.10})
        assert result.health_score < 100.0
