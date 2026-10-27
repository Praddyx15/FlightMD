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


def test_nothing_assessed_is_not_100_a():
    """A file with no analysable telemetry used to score 100 / A."""
    results = [result(n, skipped=True) for n in ("oscillation", "vibration", "ekf", "battery", "gps")]
    score, label, grade = ScoreCalculator().calculate(results)
    assert (score, label, grade) == (0.0, "Not assessed", "-")
    assert all(not r.assessed for r in results)


def test_empty_results_not_assessed():
    assert ScoreCalculator().calculate([])[1] == "Not assessed"


def test_unweighted_module_alone_is_not_assessed():
    assert ScoreCalculator().calculate([result("ascent_profile")])[1] == "Not assessed"


def test_analyser_health_score_is_used_as_computed():
    """The analyser's own caps and extra penalties used to be overwritten by
    a flat per-finding sum."""
    f = Finding(category=Category.EKF, severity=Severity.WARNING, title="x",
                technical_summary="x", plain_english="x", recommendation="x", confidence=1.0)
    results = [result("ekf", score=62.0, findings=[f])]
    score, _, _ = ScoreCalculator().calculate(results)
    assert score == 62.0
    assert results[0].health_score == 62.0


def test_skipped_modules_dont_count():
    results = [result("oscillation", 80.0), result("vibration", skipped=True)]
    assert ScoreCalculator().calculate(results)[0] == 80.0


def test_weighted_mean():
    results = [result("oscillation", 50.0), result("parameters", 100.0)]   # weights 20, 5
    assert ScoreCalculator().calculate(results)[0] == 60.0


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


def test_assessed_fraction():
    results = [result("oscillation"), result("vibration"), result("ekf", skipped=True)]
    ScoreCalculator().calculate(results)
    assert ScoreCalculator().assessed_fraction(results) == 0.4
