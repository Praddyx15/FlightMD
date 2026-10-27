"""
The published JSON Schema (docs/schema/) must match the report model, and
every schema version must be in the changelog.
"""

import json
from pathlib import Path

from flightmd_core.models.findings import FlightMDReport

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"
VERSION = FlightMDReport.model_fields["schema_version"].default


def normalise(node):
    # pydantic >= 2.11 writes additionalProperties: true for a bare dict,
    # 2.10 leaves it out; both mean "any keys"
    if isinstance(node, dict):
        return {k: normalise(v) for k, v in node.items()
                if not (k == "additionalProperties" and v is True)}
    if isinstance(node, list):
        return [normalise(v) for v in node]
    return node


def test_published_schema_matches_the_model():
    path = SCHEMA_DIR / f"flightmd-report-{VERSION}.json"
    assert path.exists(), f"run scripts/export_schema.py to publish schema {VERSION}"
    published = json.loads(path.read_text(encoding="utf-8"))
    assert normalise(published) == normalise(FlightMDReport.model_json_schema())


def test_changelog_lists_the_current_version():
    assert f"## {VERSION}" in (SCHEMA_DIR / "CHANGELOG.md").read_text(encoding="utf-8")


def test_finding_params_is_in_the_schema():
    finding = json.loads((SCHEMA_DIR / f"flightmd-report-{VERSION}.json").read_text(encoding="utf-8"))
    props = finding["$defs"]["Finding"]["properties"]
    assert props["params"] == {"default": [], "items": {"type": "string"}, "title": "Params", "type": "array"}


def test_a_1_6_report_still_loads():
    old = {
        "report_id": "r1", "schema_version": "1.6", "overall_score": 80.0, "score_label": "Good",
        "letter_grade": "B", "executive_summary": "s", "metadata": {"duration_seconds": 60.0},
        "findings": [{
            "category": "oscillation", "severity": "warning", "title": "t",
            "technical_summary": "x", "plain_english": "x", "recommendation": "x", "confidence": 0.8,
            "param_changes": [{"param_name": "MC_ROLLRATE_P", "current_value": 0.2,
                               "suggested_value": 0.17, "change_direction": "decrease", "reason": "r"}],
        }],
        "param_change_sheet": [], "analyser_results": [], "processing_time_ms": 1,
        "file_name": "f.ulg", "file_size_bytes": 1,
    }
    report = FlightMDReport.model_validate(old)
    assert report.schema_version == "1.6"
    assert report.generated_at is None
    assert report.findings[0].params == ["MC_ROLLRATE_P"]
