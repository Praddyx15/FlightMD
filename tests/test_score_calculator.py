"""
Tests for ScoreCalculator — not-assessed handling, analyser scores, bands.
"""

import pytest

from flightmd_core.models.findings import AnalyserResult, Finding, Category, Severity
from flightmd_core.services.score_calculator import ScoreCalculator


def result(name, score=100.0, skipped=False, findings=None):
    return AnalyserResult(
        analyser=name, display_name=name.title(), findings=findings or [],
        health_score=score, skipped=skipped, skip_reason="no data" if skipped else None,
    )


# covers: HLR-RPT-005, HLR-RPT-003, LLR-RPT-009, LLR-RPT-016, LLR-RPT-017
def test_nothing_assessed_is_not_100_a():
    """A file with no analysable telemetry used to score 100 / A."""
    results = [result(n, skipped=True) for n in ("oscillation", "vibration", "ekf", "battery", "gps")]
    score, label, grade = ScoreCalculator().calculate(results)
    assert (score, label, grade) == (0.0, "Not assessed", "-")
    assert all(not r.assessed for r in results)


# covers: HLR-RPT-005, LLR-RPT-017
def test_empty_results_not_assessed():
    assert ScoreCalculator().calculate([])[1] == "Not assessed"


# covers: HLR-RPT-005, LLR-RPT-016, LLR-RPT-017
def test_unweighted_module_alone_is_not_assessed():
    assert ScoreCalculator().calculate([result("ascent_profile")])[1] == "Not assessed"


# covers: HLR-RPT-004, LLR-RPT-015
def test_analyser_health_score_is_used_as_computed():
    """The analyser's own caps and extra penalties used to be overwritten by
    a flat per-finding sum."""
    f = Finding(category=Category.EKF, severity=Severity.WARNING, title="x",
                technical_summary="x", plain_english="x", recommendation="x", confidence=1.0)
    results = [result("ekf", score=62.0, findings=[f])]
    score, _, _ = ScoreCalculator().calculate(results)
    assert score == 62.0
    assert results[0].health_score == 62.0


# covers: HLR-RPT-004, LLR-RPT-016
def test_skipped_modules_dont_count():
    results = [result("oscillation", 80.0), result("vibration", skipped=True)]
    assert ScoreCalculator().calculate(results)[0] == 80.0


# covers: HLR-RPT-004, LLR-RPT-015
def test_weighted_mean():
    results = [result("oscillation", 50.0), result("parameters", 100.0)]   # weights 20, 5
    assert ScoreCalculator().calculate(results)[0] == 60.0


# covers: HLR-RPT-006, LLR-RPT-018
@pytest.mark.parametrize("score, label, grade", [
    (95, "Excellent", "A"),
    (90, "Excellent", "A"),
    (85, "Good", "B"),
    (78, "Caution", "C"),
    (72, "Caution", "C"),
    (65, "Caution", "D"),
    (55, "Warning", "E"),
    (30, "Critical", "F"),
])
def test_label_and_grade_agree(score, label, grade):
    calc = ScoreCalculator()
    assert calc._label(score) == label
    assert calc.get_letter_grade(score) == grade


# covers: HLR-RPT-007, LLR-RPT-019
def test_assessed_fraction():
    results = [result("oscillation"), result("vibration"), result("ekf", skipped=True)]
    ScoreCalculator().calculate(results)
    assert ScoreCalculator().assessed_fraction(results) == 0.4


# covers: LLR-RPT-014
def test_weights_come_from_the_analyser_classes():
    w = ScoreCalculator().weights
    assert w["oscillation"] == 20.0
    assert w["parameters"] == 5.0
    assert "ascent_profile" not in w
    assert "power" not in w


# covers: LLR-RPT-014, LLR-RPT-015, LLR-RPT-019
def test_custom_weights():
    calc = ScoreCalculator({"x": 1.0, "y": 3.0})
    assert calc.calculate([result("x", 0.0), result("y", 100.0)])[0] == 75.0
    assert calc.assessed_fraction([result("y")]) == 0.75


# covers: HLR-RPT-004, LLR-RPT-020
def test_nan_module_score_counts_as_zero_not_100():
    """PR-002: min(100.0, nan) is 100.0, so a NaN module score used to count as perfect."""
    results = [result("oscillation", float("nan")), result("parameters", 100.0)]   # weights 20, 5
    score, _, _ = ScoreCalculator().calculate(results)
    assert score == 20.0
    assert results[0].health_score == 0.0


# covers: LLR-RPT-020
def test_infinite_module_scores_are_held_to_the_range():
    results = [result("oscillation", float("inf")), result("vibration", float("-inf"))]
    ScoreCalculator().calculate(results)
    assert [r.health_score for r in results] == [100.0, 0.0]


# covers: HLR-RPT-004, LLR-RPT-016
def test_zero_weight_module_never_moves_the_score():
    results = [result("oscillation", 80.0), result("power", 0.0)]
    assert ScoreCalculator().calculate(results)[0] == 80.0
