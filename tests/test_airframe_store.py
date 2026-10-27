"""
AirframeConfigStore: maintenance log, checklist, alert rules, airframe tokens.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.airframe_store import (
    AirframeConfigStore, AlertRule, MaintenanceEntry, TokenError,
    _slugify, evaluate_alert_rules, extract_metric_value, hash_token,
)
from flightmd_core.models.findings import AnalyserResult, FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report(score=85.0) -> FlightMDReport:
    return FlightMDReport(
        report_id="r1", overall_score=score, score_label="Good", letter_grade="B",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=600.0),
        findings=[], param_change_sheet=[],
        analyser_results=[
            AnalyserResult(analyser="battery", display_name="Battery", findings=[],
                            health_score=80.0, key_metrics={"sag_per_cell_v": 0.6}),
            AnalyserResult(analyser="oscillation", display_name="Oscillation", findings=[],
                            health_score=100.0, key_metrics={"roll_peak_hz": 0.3}),
        ],
        processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
    )


@pytest.fixture
def store(tmp_path):
    return AirframeConfigStore(data_dir=str(tmp_path))


class TestAirframeConfigStore:
    def test_get_returns_default_for_unknown_airframe(self, store):
        config = store.get("Quad-1")
        assert config.airframe_label == "Quad-1"
        assert config.checklist_items == []
        assert config.maintenance_log == []

    def test_save_and_reload_round_trips(self, store):
        config = store.get("Quad-1")
        config.checklist_items = ["Check props", "Check battery"]
        store.save(config)

        reloaded = store.get("Quad-1")
        assert reloaded.checklist_items == ["Check props", "Check battery"]

    def test_add_maintenance_entry_persists_and_sorts(self, store):
        store.add_maintenance_entry("Quad-1", MaintenanceEntry(date="2026-06-01", maintenance_type="Prop swap"))
        store.add_maintenance_entry("Quad-1", MaintenanceEntry(date="2026-01-01", maintenance_type="Motor service"))

        config = store.get("Quad-1")
        assert [m.date for m in config.maintenance_log] == ["2026-01-01", "2026-06-01"]

    def test_update_settings_partial_update_preserves_other_fields(self, store):
        store.update_settings("Quad-1", checklist_items=["A"])
        store.update_settings("Quad-1", maintenance_interval_hours=10.0)

        config = store.get("Quad-1")
        assert config.checklist_items == ["A"]
        assert config.maintenance_interval_hours == 10.0

    def test_labels_with_special_characters_get_a_safe_filename(self, store):
        store.update_settings("Quad #1 / Test", checklist_items=["A"])
        config = store.get("Quad #1 / Test")
        assert config.checklist_items == ["A"]
        assert config.airframe_label == "Quad #1 / Test"

    def test_labels_with_the_same_slug_do_not_collide(self, store):
        store.update_settings("Quad 1", checklist_items=["space"])
        store.update_settings("Quad_1", checklist_items=["underscore"])
        store.update_settings("Quad#1", checklist_items=["hash"])

        assert store.get("Quad 1").checklist_items == ["space"]
        assert store.get("Quad_1").checklist_items == ["underscore"]
        assert store.get("Quad#1").checklist_items == ["hash"]

    def test_none_clears_a_field_and_omitted_fields_stay(self, store):
        store.update_settings("Quad-1", checklist_items=["A"], maintenance_interval_hours=10.0)
        store.update_settings("Quad-1", maintenance_interval_hours=None)

        config = store.get("Quad-1")
        assert config.maintenance_interval_hours is None
        assert config.checklist_items == ["A"]

    def test_corrupt_file_raises_instead_of_being_overwritten(self, store, tmp_path):
        store.update_settings("Quad-1", checklist_items=["A"])
        path = store._path("Quad-1")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")

        with pytest.raises(ValueError):
            store.update_settings("Quad-1", checklist_items=["B"])
        with open(path, encoding="utf-8") as f:
            assert f.read() == "{not json"

    def test_legacy_slug_file_is_read_and_migrated(self, store, tmp_path):
        legacy = tmp_path / f"{_slugify('Quad 1')}.json"
        legacy.write_text(json.dumps({"airframe_label": "Quad 1", "checklist_items": ["old"]}), encoding="utf-8")

        assert store.get("Quad 1").checklist_items == ["old"]
        # a different label with the same slug must not see it
        assert store.get("Quad_1").checklist_items == []

        store.update_settings("Quad 1", checklist_items=["new"])
        assert not legacy.exists()
        assert store.get("Quad 1").checklist_items == ["new"]


class TestAirframeTokens:
    def test_first_claim_returns_a_token_and_stores_only_its_hash(self, store):
        token = store.authorise("Quad-1", None, claim=True)
        assert token

        with open(store._path("Quad-1"), encoding="utf-8") as f:
            raw = f.read()
        assert token not in raw
        assert hash_token(token) in raw

    def test_token_never_in_public_dict(self, store):
        store.authorise("Quad-1", None, claim=True)
        assert "token_hash" not in store.get("Quad-1").to_dict()

    def test_claimed_airframe_needs_the_right_token(self, store):
        token = store.authorise("Quad-1", None, claim=True)

        with pytest.raises(TokenError) as missing:
            store.authorise("Quad-1", None, claim=True)
        assert missing.value.reason == "missing"

        with pytest.raises(TokenError) as wrong:
            store.authorise("Quad-1", "guess", claim=True)
        assert wrong.value.reason == "invalid"

        assert store.authorise("Quad-1", token) is None

    def test_unclaimed_airframe_cannot_be_read(self, store):
        with pytest.raises(TokenError) as e:
            store.authorise("Quad-1", None)
        assert e.value.reason == "unclaimed"

    def test_existing_config_without_token_is_claimed_by_first_write(self, store):
        store.update_settings("Quad-1", checklist_items=["A"])
        token = store.authorise("Quad-1", None, claim=True)
        assert token
        assert store.get("Quad-1").checklist_items == ["A"]

    def test_settings_updates_keep_the_token(self, store):
        token = store.authorise("Quad-1", None, claim=True)
        store.update_settings("Quad-1", checklist_items=["A"])
        store.add_maintenance_entry("Quad-1", MaintenanceEntry(date="2026-01-01", maintenance_type="Props"))
        assert store.authorise("Quad-1", token) is None


class TestAlertRuleValidation:
    def test_invalid_comparison_rejected(self):
        with pytest.raises(ValueError):
            AlertRule(metric="overall_score", comparison="equals", threshold=50.0)

    def test_invalid_metric_name_rejected(self):
        with pytest.raises(ValueError):
            AlertRule(metric="oh no; drop table", comparison="lt", threshold=50.0)


class TestExtractMetricValue:
    def test_overall_score(self):
        assert extract_metric_value(make_report(72.0), "overall_score") == 72.0

    def test_module_score(self):
        assert extract_metric_value(make_report(), "module.battery") == 80.0

    def test_key_metric(self):
        assert extract_metric_value(make_report(), "battery.sag_per_cell_v") == 0.6

    def test_missing_module_returns_none(self):
        assert extract_metric_value(make_report(), "module.gps") is None

    def test_missing_key_metric_returns_none(self):
        assert extract_metric_value(make_report(), "battery.nonexistent") is None


class TestEvaluateAlertRules:
    def test_breach_detected_lt(self):
        rules = [AlertRule(metric="overall_score", comparison="lt", threshold=90.0, label="Score too low")]
        triggered = evaluate_alert_rules(make_report(85.0), rules)
        assert len(triggered) == 1
        assert triggered[0]["value"] == 85.0

    def test_breach_detected_gt(self):
        rules = [AlertRule(metric="battery.sag_per_cell_v", comparison="gt", threshold=0.5, label="Battery sag")]
        triggered = evaluate_alert_rules(make_report(), rules)
        assert len(triggered) == 1

    def test_no_breach_when_within_threshold(self):
        rules = [AlertRule(metric="overall_score", comparison="lt", threshold=50.0)]
        triggered = evaluate_alert_rules(make_report(85.0), rules)
        assert triggered == []

    def test_rule_referencing_missing_metric_is_skipped_not_breached(self):
        rules = [AlertRule(metric="gps.max_hdop", comparison="gt", threshold=2.0)]
        triggered = evaluate_alert_rules(make_report(), rules)
        assert triggered == []
