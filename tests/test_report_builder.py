"""
Tests for ReportBuilder — parameter-sheet dedupe, NaN sanitising, schema version.
"""

import json
import math
import re

from flightmd_core.models.findings import (
    AnalyserResult, Finding, Category, Severity, ParamRecommendation,
)
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.report_builder import ReportBuilder


def rec(name, cur, new, direction, reason="r"):
    return ParamRecommendation(param_name=name, current_value=cur, suggested_value=new,
                               change_direction=direction, reason=reason)


def finding(severity, changes=(), title="t", chart=None, confidence=0.8):
    return Finding(category=Category.OSCILLATION, severity=severity, title=title,
                   technical_summary="x", plain_english="x", recommendation="x",
                   confidence=confidence, param_changes=list(changes), chart_data=chart)


def build(findings, results=None, metadata=None, score=(90.0, "Excellent", "A")):
    results = results or [AnalyserResult(analyser="oscillation", display_name="Oscillation",
                                         findings=findings)]
    return ReportBuilder().build(
        results=results, findings=findings,
        metadata=metadata or FlightMetadata(duration_seconds=60.0),
        score=score, executive_summary="s", file_name="f.ulg", file_size=10,
    )


def test_schema_version_is_current():
    assert build([]).schema_version == "1.7"


def test_generated_at_is_utc_iso():
    stamp = build([]).generated_at
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp)


def test_params_list_includes_param_changes():
    f = finding(Severity.WARNING, [rec("MC_ROLLRATE_D", 0.004, 0.0034, "decrease")])
    f.params = ["IMU_DGYRO_CUTOFF"]
    [out] = build([f]).findings
    assert out.params == ["IMU_DGYRO_CUTOFF", "MC_ROLLRATE_D"]


def test_change_appended_after_construction_reaches_params():
    f = finding(Severity.WARNING)
    f.param_changes.append(rec("MPC_XY_P", 1.8, 0.95, "decrease"))
    [out] = build([f]).findings
    assert out.params == ["MPC_XY_P"]


def test_conflicting_directions_keep_the_more_severe_and_say_so():
    warn = finding(Severity.WARNING, [rec("MC_ROLLRATE_P", 0.2, 0.17, "decrease")], title="Roll oscillation")
    info = finding(Severity.INFO, [rec("MC_ROLLRATE_P", 0.2, 0.3, "increase")], title="Below range")
    sheet = build([info, warn]).param_change_sheet
    assert len(sheet) == 1
    assert sheet[0].change_direction == "decrease"
    assert sheet[0].suggested_value == 0.17
    assert "increase to 0.3" in sheet[0].reason


def test_same_direction_keeps_first_without_note():
    a = finding(Severity.CRITICAL, [rec("BAT_LOW_THR", 0.05, 0.15, "increase", "inverted")])
    b = finding(Severity.WARNING, [rec("BAT_LOW_THR", 0.05, 0.12, "increase", "below range")])
    sheet = build([b, a]).param_change_sheet
    assert [(r.suggested_value, r.reason) for r in sheet] == [(0.15, "inverted")]


def test_dedupe_does_not_mutate_finding_cards():
    warn = finding(Severity.WARNING, [rec("X", 1, 0.5, "decrease", "orig")])
    info = finding(Severity.INFO, [rec("X", 1, 2, "increase")])
    build([warn, info])
    assert warn.param_changes[0].reason == "orig"


def test_nan_never_reaches_json():
    chart = {"timestamps": [0.0, 1.0], "hdop": [1.0, float("nan")], "peak": float("inf")}
    f = finding(Severity.WARNING, chart=chart)
    results = [AnalyserResult(analyser="gps", display_name="GPS", findings=[f],
                              key_metrics={"max_hdop": float("nan"), "min_satellites": 7.0})]
    meta = FlightMetadata(duration_seconds=float("nan"), max_altitude_m=float("nan"),
                          gps_path_hdop=[1.0, float("nan")])
    report = build([f], results=results, metadata=meta)

    text = json.dumps(report.model_dump(mode="json"), allow_nan=False)
    assert "NaN" not in text
    assert report.findings[0].chart_data["hdop"] == [1.0, None]
    assert report.findings[0].chart_data["peak"] is None
    assert report.analyser_results[0].key_metrics == {"min_satellites": 7.0}
    assert report.metadata.max_altitude_m is None
    assert report.metadata.duration_seconds == 0.0
    assert report.metadata.gps_path_hdop == [1.0, None]


def test_nan_confidence_becomes_zero():
    f = finding(Severity.INFO, confidence=float("nan"))
    assert f.confidence == 0.0 and f.confidence_level == "low"


def test_findings_sorted_by_severity_then_confidence():
    a = finding(Severity.INFO, title="a")
    b = finding(Severity.CRITICAL, title="b", confidence=0.5)
    c = finding(Severity.CRITICAL, title="c", confidence=0.9)
    assert [f.title for f in build([a, b, c]).findings] == ["c", "b", "a"]


def test_assessed_fraction_and_not_assessed_score():
    results = [AnalyserResult(analyser="oscillation", display_name="O", findings=[], skipped=True)]
    report = build([], results=results, score=(0.0, "Not assessed", "-"))
    assert report.assessed_fraction == 0.0
    assert report.score_label == "Not assessed"
    assert not math.isnan(report.overall_score)


def test_time_window_fields_filled_from_ms():
    f = Finding(category=Category.GPS, severity=Severity.WARNING, title="t", technical_summary="x",
                plain_english="x", recommendation="x", confidence=0.5,
                timestamp_start_ms=12_500, timestamp_end_ms=20_000)
    assert (f.t_start_s, f.t_end_s) == (12.5, 20.0)
