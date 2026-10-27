"""
GET /trends/{airframe_label} and GET /diff.

Fills the job_store singleton directly (pointed at a temp dir) instead of
running uploads; both endpoints only reshape finished reports.
"""

import os
import sys

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flightmd_core.models.findings import (
    AnalyserResult, FlightMDReport, Finding, Severity, Category
)
from flightmd_core.models.metadata import FlightMetadata


def make_report(report_id: str, score: float, roll_hz: float, sag_v: float,
                 findings: list[Finding] = None, battery_skipped: bool = False) -> FlightMDReport:
    meta = FlightMetadata(duration_seconds=120.0, firmware_version="1.14.0")
    return FlightMDReport(
        report_id=report_id,
        overall_score=score,
        score_label="Good",
        letter_grade="B",
        executive_summary="Summary",
        metadata=meta,
        findings=findings or [],
        param_change_sheet=[],
        analyser_results=[
            AnalyserResult(
                analyser="oscillation", display_name="Oscillation Analysis",
                findings=[], health_score=100.0,
                key_metrics={"roll_peak_hz": roll_hz},
            ),
            AnalyserResult(
                analyser="battery", display_name="Battery Analysis",
                findings=[], health_score=100.0, skipped=battery_skipped,
                key_metrics={"sag_per_cell_v": sag_v},
            ),
        ],
        processing_time_ms=10,
        file_name=f"{report_id}.ulg",
        file_size_bytes=1024,
    )


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    from api import airframe_store as afs
    from api.storage import JobStore, job_store

    (tmp_path / "reports").mkdir()
    (tmp_path / "airframes").mkdir()
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(job_store, "_store", {})
    monkeypatch.setattr(afs.airframe_store, "data_dir", str(tmp_path / "airframes"))

    from api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, job_store


def claim(label):
    from api import airframe_store as afs
    return {"X-Airframe-Token": afs.airframe_store.authorise(label, None, claim=True)}


class TestTrendsEndpoint:
    @pytest.mark.asyncio
    async def test_unclaimed_airframe_needs_a_token(self, client):
        c, _ = client
        resp = await c.get("/trends/NoSuchDrone")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self, client):
        c, _ = client
        claim("Quad-1")
        resp = await c.get("/trends/Quad-1", headers={"X-Airframe-Token": "guess"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_flights_for_a_new_airframe(self, client):
        c, _ = client
        resp = await c.get("/trends/NoSuchDrone", headers=claim("NoSuchDrone"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["flight_count"] == 0
        assert data["flights"] == []

    @pytest.mark.asyncio
    async def test_returns_time_series_across_tagged_flights(self, client):
        c, store = client
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1", score=80.0, roll_hz=0.5, sag_v=0.2))
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2", score=70.0, roll_hz=1.1, sag_v=0.6))
        store.create("r3", airframe_label="Other-Drone")
        store.complete("r3", make_report("r3", score=95.0, roll_hz=0.1, sag_v=0.1))

        resp = await c.get("/trends/Quad-1", headers=claim("Quad-1"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["flight_count"] == 2
        report_ids = [f["report_id"] for f in data["flights"]]
        assert report_ids == ["r1", "r2"]
        assert data["flights"][1]["key_metrics"]["oscillation.roll_peak_hz"] == 1.1
        assert data["flights"][1]["key_metrics"]["battery.sag_per_cell_v"] == 0.6
        assert data["flights"][0]["module_scores"]["oscillation"] == 100.0


    @pytest.mark.asyncio
    async def test_skipped_module_score_is_null_not_100(self, client):
        c, store = client
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1", 80.0, 0.5, 0.2, battery_skipped=True))

        resp = await c.get("/trends/Quad-1", headers=claim("Quad-1"))
        scores = resp.json()["flights"][0]["module_scores"]
        assert scores["battery"] is None
        assert scores["oscillation"] == 100.0


class TestDiffEndpoint:
    @pytest.mark.asyncio
    async def test_diff_two_flights_score_delta(self, client):
        c, store = client
        store.create("r1")
        store.complete("r1", make_report("r1", score=70.0, roll_hz=1.1, sag_v=0.6))
        store.create("r2")
        store.complete("r2", make_report("r2", score=90.0, roll_hz=0.3, sag_v=0.2))

        resp = await c.get("/diff", params={"a": "r1", "b": "r2"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_score_delta"] == 20.0
        assert data["key_metric_deltas"]["oscillation.roll_peak_hz"]["delta"] == pytest.approx(-0.8)

    @pytest.mark.asyncio
    async def test_diff_reports_resolved_and_new_findings(self, client):
        c, store = client
        finding_a = Finding(
            category=Category.OSCILLATION, severity=Severity.WARNING,
            title="Roll-Axis Oscillation at 1.1 Hz", technical_summary="t",
            plain_english="p", recommendation="r", confidence=0.9,
        )
        finding_b = Finding(
            category=Category.GPS, severity=Severity.WARNING,
            title="GPS Satellite Count Drop", technical_summary="t",
            plain_english="p", recommendation="r", confidence=0.5,
        )
        store.create("r1")
        store.complete("r1", make_report("r1", 70.0, 1.1, 0.6, findings=[finding_a]))
        store.create("r2")
        store.complete("r2", make_report("r2", 90.0, 0.3, 0.2, findings=[finding_b]))

        resp = await c.get("/diff", params={"a": "r1", "b": "r2"})
        data = resp.json()
        assert data["findings_diff"]["resolved"] == ["Roll-Axis Oscillation at 1.1 Hz"]
        assert data["findings_diff"]["new"] == ["GPS Satellite Count Drop"]

    @pytest.mark.asyncio
    async def test_diff_same_report_rejected(self, client):
        c, store = client
        store.create("r1")
        store.complete("r1", make_report("r1", 70.0, 1.1, 0.6))

        resp = await c.get("/diff", params={"a": "r1", "b": "r1"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_diff_skipped_module_has_no_delta(self, client):
        c, store = client
        store.create("r1")
        store.complete("r1", make_report("r1", 70.0, 1.1, 0.6, battery_skipped=True))
        store.create("r2")
        store.complete("r2", make_report("r2", 90.0, 0.3, 0.2))

        data = (await c.get("/diff", params={"a": "r1", "b": "r2"})).json()
        assert data["module_score_deltas"]["battery"] == {"a": None, "b": 100.0, "delta": None}

    @pytest.mark.asyncio
    async def test_diff_missing_report_404s(self, client):
        c, _ = client
        resp = await c.get("/diff", params={"a": "nonexistent-a", "b": "nonexistent-b"})
        assert resp.status_code == 404
