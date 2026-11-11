"""
GET /metrics: Prometheus text, protected by METRICS_TOKEN when it is set,
analysis counters by format/outcome, and nothing identifying in the labels.
"""

import io
import os
import sys

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import db, metrics


@pytest.fixture
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest_asyncio.fixture
async def client(database, monkeypatch):
    from api.config import get_settings
    from api.security import limiter
    monkeypatch.setattr(get_settings(), "metrics_token", "")
    limiter.reset()
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def sample(name, **labels):
    from prometheus_client import REGISTRY
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestAuth:
    @pytest.mark.asyncio
    async def test_open_when_no_token_is_set(self, client):
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "flightmd_analyses_total" in resp.text

    @pytest.mark.asyncio
    async def test_token_required_when_set(self, client, monkeypatch):
        from api.config import get_settings
        monkeypatch.setattr(get_settings(), "metrics_token", "s3cret")

        assert (await client.get("/metrics")).status_code == 401
        assert (await client.get("/metrics", headers={"Authorization": "Basic s3cret"})).status_code == 401
        assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 403
        resp = await client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_not_in_the_openapi_schema(self, client):
        assert "/metrics" not in (await client.get("/openapi.json")).json()["paths"]


class TestCounters:
    def test_unknown_formats_and_outcomes_are_bucketed(self):
        before = sample("flightmd_analyses_total", format="other", outcome="error")
        metrics.count_analysis("../../etc/passwd", "something-new")
        assert sample("flightmd_analyses_total", format="other", outcome="error") == before + 1

    def test_duration_histogram(self):
        before = sample("flightmd_analysis_duration_seconds_count", format="px4_ulog")
        metrics.observe_duration("px4_ulog", 3.2)
        assert sample("flightmd_analysis_duration_seconds_count", format="px4_ulog") == before + 1

    @pytest.mark.asyncio
    async def test_finished_job_is_counted(self, client, monkeypatch, tmp_path):
        import api.analysis as analysis_module
        from api.analysis import AnalysisJob, run_job
        from api.storage import job_store

        async def rejecting(**kwargs):
            raise ValueError("no analysable telemetry")
        monkeypatch.setattr(analysis_module, "run_analysis", rejecting)

        before = sample("flightmd_analyses_total", format="ardupilot_bin", outcome="rejected")
        job_store.create("r1")
        await run_job(AnalysisJob(report_id="r1", log_path=str(tmp_path / "x"), file_name="secret-site.bin",
                                  file_size=1, log_format="ardupilot_bin"))
        assert sample("flightmd_analyses_total", format="ardupilot_bin", outcome="rejected") == before + 1

    @pytest.mark.asyncio
    async def test_labels_never_carry_ids_or_filenames(self, client, monkeypatch):
        import api.routers.analyse as analyse_module

        class Sink:
            async def submit(self, job):
                pass
        monkeypatch.setattr(analyse_module, "get_queue", lambda: Sink())

        resp = await client.post("/analyse", files={
            "file": ("JohnSmith_farm.ulg", io.BytesIO(b"ULog\x01\x12\x35\x01" + b"\x00" * 100), "application/octet-stream"),
        })
        report_id = resp.json()["report_id"]
        await client.get(f"/status/{report_id}")

        text = (await client.get("/metrics")).text
        assert report_id not in text
        assert "JohnSmith" not in text
        assert 'handler="/status/{report_id}"' in text
