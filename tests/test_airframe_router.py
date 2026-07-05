"""
Tests for the /airframe/{label}/config and /airframe/{label}/maintenance
endpoints.
"""

import os
import sys

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    from api.airframe_store import AirframeConfigStore
    import api.airframe_store as airframe_store_module
    airframe_store_module.airframe_store = AirframeConfigStore(data_dir=str(tmp_path / "airframes"))
    monkeypatch.setattr("api.routers.airframe.airframe_store", airframe_store_module.airframe_store)

    from api.storage import JobStore
    import api.storage as storage_module
    storage_module.job_store = JobStore()
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path / "reports"))
    storage_module.job_store = JobStore()
    monkeypatch.setattr("api.routers.airframe.job_store", storage_module.job_store)

    from api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_unknown_airframe_returns_default_config(self, client):
        resp = await client.get("/airframe/Quad-1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["airframe_label"] == "Quad-1"
        assert data["checklist_items"] == []
        assert data["flight_count"] == 0
        assert data["maintenance_due"] is False

    @pytest.mark.asyncio
    async def test_invalid_label_rejected(self, client):
        resp = await client.get("/airframe/%20/config")
        assert resp.status_code == 400


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_set_checklist_items(self, client):
        resp = await client.put("/airframe/Quad-1/config", json={"checklist_items": ["Check props", "Check GPS lock"]})
        assert resp.status_code == 200
        assert resp.json()["checklist_items"] == ["Check props", "Check GPS lock"]

    @pytest.mark.asyncio
    async def test_set_alert_rules(self, client):
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "overall_score", "comparison": "lt", "threshold": 70.0, "label": "Score drop"}]
        })
        assert resp.status_code == 200
        assert resp.json()["alert_rules"][0]["metric"] == "overall_score"

    @pytest.mark.asyncio
    async def test_invalid_alert_rule_comparison_rejected_by_pydantic(self, client):
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "overall_score", "comparison": "equals", "threshold": 70.0}]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_alert_rule_metric_rejected(self, client):
        """Pydantic's AlertRuleBody accepts any metric string — the METRIC_NAME_RE
        check only lives in AlertRule.__post_init__, so this exercises the
        router's own try/except ValueError -> 400 path specifically."""
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "oh no; drop table", "comparison": "lt", "threshold": 70.0}]
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unsafe_webhook_url_rejected(self, client):
        resp = await client.put("/airframe/Quad-1/config", json={"webhook_url": "http://127.0.0.1/hook"})
        assert resp.status_code == 400


class TestMaintenanceEntry:
    @pytest.mark.asyncio
    async def test_add_entry(self, client):
        resp = await client.post("/airframe/Quad-1/maintenance", json={
            "date": "2026-06-01", "maintenance_type": "Propeller replacement", "notes": "All 4 props"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["maintenance_log"]) == 1
        assert data["maintenance_log"][0]["maintenance_type"] == "Propeller replacement"

    @pytest.mark.asyncio
    async def test_invalid_date_rejected(self, client):
        resp = await client.post("/airframe/Quad-1/maintenance", json={
            "date": "not-a-date", "maintenance_type": "Prop swap"
        })
        assert resp.status_code == 400
