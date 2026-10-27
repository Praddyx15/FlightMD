"""
/airframe/{label}/config, /airframe/{label}/maintenance and the airframe PDF:
every one needs the airframe's X-Airframe-Token, and the first write claims it.
"""

import os
import sys
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def database(tmp_path, monkeypatch):
    from api import db
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest_asyncio.fixture
async def client(database):
    from api.security import limiter
    limiter.reset()

    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def claim(client, label="Quad-1"):
    resp = await client.put(f"/airframe/{label}/config", json={})
    assert resp.status_code == 200
    return resp.json()["airframe_token"]


def auth(token):
    return {"X-Airframe-Token": token}


class TestClaiming:
    @pytest.mark.asyncio
    async def test_unclaimed_airframe_cannot_be_read(self, client):
        resp = await client.get("/airframe/Quad-1/config")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_first_put_returns_token_once(self, client):
        token = await claim(client)

        resp = await client.get("/airframe/Quad-1/config", headers=auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["airframe_label"] == "Quad-1"
        assert data["checklist_items"] == []
        assert data["flight_count"] == 0
        assert data["maintenance_due"] is False
        assert "airframe_token" not in data
        assert "token_hash" not in data

    @pytest.mark.asyncio
    async def test_claimed_airframe_rejects_missing_and_wrong_tokens(self, client):
        await claim(client)

        assert (await client.get("/airframe/Quad-1/config")).status_code == 401
        assert (await client.get("/airframe/Quad-1/config", headers=auth("nope"))).status_code == 403

    @pytest.mark.asyncio
    async def test_webhook_cannot_be_taken_over(self, client):
        await claim(client)
        resp = await client.put("/airframe/Quad-1/config", json={"webhook_url": "https://attacker.example/hook"})
        assert resp.status_code == 401
        resp = await client.put(
            "/airframe/Quad-1/config", json={"webhook_url": "https://attacker.example/hook"}, headers=auth("guess"),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_maintenance_post_also_claims(self, client):
        resp = await client.post("/airframe/Quad-2/maintenance", json={
            "date": "2026-06-01", "maintenance_type": "Prop swap",
        })
        assert resp.status_code == 200
        assert resp.json()["airframe_token"]

    @pytest.mark.asyncio
    async def test_rejected_body_does_not_consume_the_claim(self, client):
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "oh no; drop table", "comparison": "lt", "threshold": 70.0}]
        })
        assert resp.status_code == 400
        assert await claim(client)

    @pytest.mark.asyncio
    async def test_invalid_label_rejected(self, client):
        resp = await client.get("/airframe/%20/config")
        assert resp.status_code == 400


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_set_checklist_items(self, client):
        token = await claim(client)
        resp = await client.put("/airframe/Quad-1/config", json={"checklist_items": ["Check props", "Check GPS lock"]},
                                headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()["checklist_items"] == ["Check props", "Check GPS lock"]

    @pytest.mark.asyncio
    async def test_set_alert_rules(self, client):
        token = await claim(client)
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "overall_score", "comparison": "lt", "threshold": 70.0, "label": "Score drop"}]
        }, headers=auth(token))
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
        # AlertRuleBody takes any metric string; METRIC_NAME_RE lives in AlertRule
        resp = await client.put("/airframe/Quad-1/config", json={
            "alert_rules": [{"metric": "oh no; drop table", "comparison": "lt", "threshold": 70.0}]
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["http://127.0.0.1/hook", "https://127.0.0.1/hook", "https://10.0.0.5/hook"])
    async def test_unsafe_webhook_url_rejected(self, client, url):
        resp = await client.put("/airframe/Quad-1/config", json={"webhook_url": url})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hours", [0, -5])
    async def test_non_positive_interval_rejected(self, client, hours):
        resp = await client.put("/airframe/Quad-1/config", json={"maintenance_interval_hours": hours})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_null_clears_interval(self, client):
        token = await claim(client)
        await client.put("/airframe/Quad-1/config", json={"maintenance_interval_hours": 20}, headers=auth(token))
        resp = await client.put("/airframe/Quad-1/config", json={"maintenance_interval_hours": None}, headers=auth(token))
        assert resp.json()["maintenance_interval_hours"] is None


class TestMaintenanceEntry:
    @pytest.mark.asyncio
    async def test_add_entry(self, client):
        token = await claim(client)
        resp = await client.post("/airframe/Quad-1/maintenance", json={
            "date": "2026-06-01", "maintenance_type": "Propeller replacement", "notes": "All 4 props"
        }, headers=auth(token))
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


class TestAirframeRecordExport:
    @pytest.mark.asyncio
    async def test_needs_token(self, client):
        await claim(client)
        assert (await client.get("/export/airframe/Quad-1/pdf")).status_code == 401

    @pytest.mark.asyncio
    async def test_non_ascii_label_gets_a_valid_filename(self, client, monkeypatch):
        import api.routers.export as export_module
        monkeypatch.setattr(export_module, "render_airframe_record_pdf", lambda **kw: b"%PDF-fake")

        label = "Квадро-1"
        token = await claim(client, quote(label))
        resp = await client.get(f"/export/airframe/{quote(label)}/pdf", headers=auth(token))
        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        # six Cyrillic letters and the dash become underscores in the ascii fallback
        assert f'filename="flightmd_airframe_{"_" * 7}1.pdf"' in disposition
        assert "filename*=UTF-8''" + quote(f"flightmd_airframe_{label}.pdf") in disposition
