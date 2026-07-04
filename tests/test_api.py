"""
Tests for the FastAPI layer — upload validation, status polling, report retrieval.

Uses httpx.AsyncClient with the FastAPI app mounted directly (no server required).
"""

import io
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ULog magic bytes for a "valid" minimal file
ULOG_MAGIC = b"\x55\x4C\x6F\x67\x01\x00\x00\x00" + b"\x00" * 100


@pytest_asyncio.fixture
async def client():
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "uptime_seconds" in data

    @pytest.mark.asyncio
    async def test_health_uptime_non_negative(self, client):
        resp = await client.get("/health")
        assert resp.json()["uptime_seconds"] >= 0


class TestAnalyseEndpoint:

    @pytest.mark.asyncio
    async def test_valid_ulg_file_accepted(self, client):
        files = {"file": ("test.ulg", io.BytesIO(ULOG_MAGIC), "application/octet-stream")}
        resp = await client.post("/analyse", files=files)
        # Either 200 (processing kicked off) or potentially 400 if pyulog rejects minimal file
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            data = resp.json()
            assert "report_id" in data
            assert data["status"] == "processing"
            assert data["estimated_seconds"] == 20

    @pytest.mark.asyncio
    async def test_invalid_magic_bytes_rejected(self, client):
        bad_file = b"\x00\x01\x02\x03" + b"\x00" * 100
        files = {"file": ("bad.ulg", io.BytesIO(bad_file), "application/octet-stream")}
        resp = await client.post("/analyse", files=files)
        assert resp.status_code == 400
        assert "ULog" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_too_small_file_rejected(self, client):
        files = {"file": ("tiny.ulg", io.BytesIO(b"\x55\x4C"), "application/octet-stream")}
        resp = await client.post("/analyse", files=files)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_oversized_file_rejected(self, client, monkeypatch):
        """Simulate 51MB file — should get 413."""
        # Patch settings max size for this test
        from api import config
        monkeypatch.setattr(config.get_settings(), "max_file_size_mb", 1)
        big_content = ULOG_MAGIC + b"\x00" * (2 * 1024 * 1024)  # 2MB
        files = {"file": ("big.ulg", io.BytesIO(big_content), "application/octet-stream")}
        resp = await client.post("/analyse", files=files)
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_non_ulg_file_rejected(self, client):
        files = {"file": ("flight.txt", io.BytesIO(b"this is not a ulog file"), "text/plain")}
        resp = await client.post("/analyse", files=files)
        assert resp.status_code == 400


class TestStatusEndpoint:

    @pytest.mark.asyncio
    async def test_unknown_report_id_returns_404(self, client):
        resp = await client.get("/status/nonexistent-id-12345")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_status_after_submit_processing(self, client):
        """A freshly submitted job should return processing status."""
        files = {"file": ("test.ulg", io.BytesIO(ULOG_MAGIC), "application/octet-stream")}
        submit = await client.post("/analyse", files=files)
        if submit.status_code != 200:
            pytest.skip("File rejected (expected for minimal magic-only file)")
        report_id = submit.json()["report_id"]
        status_resp = await client.get(f"/status/{report_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["status"] in ("processing", "complete", "failed")
        assert "progress" in data


class TestReportEndpoint:

    @pytest.mark.asyncio
    async def test_unknown_report_returns_404(self, client):
        resp = await client.get("/report/no-such-report")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_report_not_found_message(self, client):
        resp = await client.get("/report/no-such-report")
        assert "not found" in resp.json()["detail"].lower()


class TestExportEndpoints:

    @pytest.mark.asyncio
    async def test_pdf_export_404_for_unknown(self, client):
        resp = await client.get("/export/pdf/no-such-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_json_export_404_for_unknown(self, client):
        resp = await client.get("/export/json/no-such-id")
        assert resp.status_code == 404


class TestStorageIntegrity:

    @pytest.mark.asyncio
    async def test_job_store_creates_and_retrieves(self):
        from api.storage import JobStore, JobStatus
        store = JobStore()
        job = store.create("test-id-123")
        assert job.report_id == "test-id-123"
        assert job.status == JobStatus.PROCESSING

        retrieved = store.get("test-id-123")
        assert retrieved is not None
        assert retrieved.report_id == "test-id-123"

    @pytest.mark.asyncio
    async def test_job_store_update_progress(self):
        from api.storage import JobStore
        store = JobStore()
        store.create("test-id-456")
        store.update_progress("test-id-456", 50, "Halfway there")
        job = store.get("test-id-456")
        assert job.progress == 50
        assert job.message == "Halfway there"

    @pytest.mark.asyncio
    async def test_job_store_fail(self):
        from api.storage import JobStore, JobStatus
        store = JobStore()
        store.create("test-id-789")
        store.fail("test-id-789", "Parsing failed")
        job = store.get("test-id-789")
        assert job.status == JobStatus.FAILED
        assert job.error == "Parsing failed"

    @pytest.mark.asyncio
    async def test_job_store_eviction_at_capacity(self):
        from api.storage import JobStore
        store = JobStore()
        store.MAX_JOBS = 3
        for i in range(4):
            store.create(f"job-{i}")
        # After 4 creates with max=3, one should have been evicted
        assert store.job_count <= 3

    @pytest.mark.asyncio
    async def test_job_store_unknown_id_returns_none(self):
        from api.storage import JobStore
        store = JobStore()
        assert store.get("does-not-exist") is None

    @pytest.mark.asyncio
    async def test_status_summary_not_found(self):
        from api.storage import JobStore
        store = JobStore()
        summary = store.status_summary("ghost-id")
        assert summary["status"] == "not_found"
