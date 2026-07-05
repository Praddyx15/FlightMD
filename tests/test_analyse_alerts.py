"""
Tests for the analyse.py alert-checking hook — evaluates a completed
tagged flight against its airframe's alert rules and fires the configured
webhook. Isolated from the actual analysis pipeline (that's covered by
test_sample_logs.py / test_api.py) and from real network calls.
"""

import pytest

import api.routers.analyse as analyse_module
from api.airframe_store import AirframeConfig, AirframeConfigStore, AlertRule
from flightmd_core.models.findings import AnalyserResult, FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report(score=60.0) -> FlightMDReport:
    return FlightMDReport(
        report_id="r1", overall_score=score, score_label="Caution", letter_grade="C",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=600.0),
        findings=[], param_change_sheet=[],
        analyser_results=[
            AnalyserResult(analyser="battery", display_name="Battery", findings=[],
                            health_score=70.0, key_metrics={"sag_per_cell_v": 0.7}),
        ],
        processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
    )


@pytest.fixture
def store(tmp_path):
    return AirframeConfigStore(data_dir=str(tmp_path))


class TestCheckAlertRules:
    @pytest.mark.asyncio
    async def test_no_rules_configured_does_nothing(self, store, monkeypatch):
        monkeypatch.setattr(analyse_module, "airframe_store", store)
        calls = []
        monkeypatch.setattr(analyse_module, "send_alert_webhook", lambda *a: calls.append(a) or True)

        await analyse_module._check_alert_rules("Quad-1", "r1", make_report())
        assert calls == []

    @pytest.mark.asyncio
    async def test_rules_but_no_webhook_does_nothing(self, store, monkeypatch):
        config = AirframeConfig(
            airframe_label="Quad-1",
            alert_rules=[AlertRule(metric="overall_score", comparison="lt", threshold=90.0)],
        )
        store.save(config)
        monkeypatch.setattr(analyse_module, "airframe_store", store)
        calls = []
        monkeypatch.setattr(analyse_module, "send_alert_webhook", lambda *a: calls.append(a) or True)

        await analyse_module._check_alert_rules("Quad-1", "r1", make_report())
        assert calls == []

    @pytest.mark.asyncio
    async def test_breached_rule_fires_webhook_with_triggered_list(self, store, monkeypatch):
        config = AirframeConfig(
            airframe_label="Quad-1",
            alert_rules=[AlertRule(metric="overall_score", comparison="lt", threshold=90.0, label="Low score")],
            webhook_url="https://example.com/hook",
        )
        store.save(config)
        monkeypatch.setattr(analyse_module, "airframe_store", store)
        calls = []
        monkeypatch.setattr(analyse_module, "send_alert_webhook", lambda *a: calls.append(a) or True)

        await analyse_module._check_alert_rules("Quad-1", "r1", make_report(score=60.0))

        assert len(calls) == 1
        webhook_url, airframe_label, report_id, triggered = calls[0]
        assert webhook_url == "https://example.com/hook"
        assert airframe_label == "Quad-1"
        assert report_id == "r1"
        assert len(triggered) == 1
        assert triggered[0]["value"] == 60.0

    @pytest.mark.asyncio
    async def test_unbreached_rule_does_not_fire_webhook(self, store, monkeypatch):
        config = AirframeConfig(
            airframe_label="Quad-1",
            alert_rules=[AlertRule(metric="overall_score", comparison="lt", threshold=10.0)],
            webhook_url="https://example.com/hook",
        )
        store.save(config)
        monkeypatch.setattr(analyse_module, "airframe_store", store)
        calls = []
        monkeypatch.setattr(analyse_module, "send_alert_webhook", lambda *a: calls.append(a) or True)

        await analyse_module._check_alert_rules("Quad-1", "r1", make_report(score=60.0))
        assert calls == []

    @pytest.mark.asyncio
    async def test_exception_in_webhook_send_is_swallowed(self, store, monkeypatch):
        config = AirframeConfig(
            airframe_label="Quad-1",
            alert_rules=[AlertRule(metric="overall_score", comparison="lt", threshold=90.0)],
            webhook_url="https://example.com/hook",
        )
        store.save(config)
        monkeypatch.setattr(analyse_module, "airframe_store", store)

        def boom(*a):
            raise RuntimeError("network exploded")
        monkeypatch.setattr(analyse_module, "send_alert_webhook", boom)

        # Must not raise — alert failures can never break the analysis job.
        await analyse_module._check_alert_rules("Quad-1", "r1", make_report(score=60.0))
