"""
Tune, fly, verify: POST/GET /airframe/{label}/changes and the verification
that compares the flight a change came from with the next tagged flight.
"""

import os
import sys
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import db
from api.param_changes import param_change_store, refresh_pending, verify
from flightmd_core.models.findings import (
    AnalyserResult, Category, FlightMDReport, Finding, ParamRecommendation, Severity,
)
from flightmd_core.models.metadata import FlightMetadata


def osc_finding(title="Roll oscillation at 6.0 Hz", kind="oscillation.roll", params=("MC_ROLLRATE_P",)):
    return Finding(
        category=Category.OSCILLATION, severity=Severity.WARNING, title=title,
        technical_summary="t", plain_english="p", recommendation="r", confidence=0.9,
        kind=kind, params=list(params),
    )


def gps_finding():
    return Finding(
        category=Category.GPS, severity=Severity.WARNING, title="GPS satellite count drop",
        technical_summary="t", plain_english="p", recommendation="r", confidence=0.5,
        kind="gps.sats", params=[],
    )


def make_report(report_id, osc_score=100.0, gps_score=100.0, overall=90.0, findings=()):
    findings = list(findings)
    return FlightMDReport(
        report_id=report_id, overall_score=overall, score_label="Good", letter_grade="B",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=300.0),
        findings=findings, param_change_sheet=[],
        analyser_results=[
            AnalyserResult(analyser="oscillation", display_name="Oscillation", health_score=osc_score,
                           findings=[f for f in findings if f.category == Category.OSCILLATION]),
            AnalyserResult(analyser="gps", display_name="GPS", health_score=gps_score,
                           findings=[f for f in findings if f.category == Category.GPS]),
        ],
        processing_time_ms=10, file_name=f"{report_id}.ulg", file_size_bytes=100,
    )


class TestVerify:
    def test_no_later_flight_is_pending(self):
        result = verify(make_report("a"), None, {"MC_ROLLRATE_P"})
        assert result == {
            "status": "pending", "next_report_id": None,
            "findings_resolved": [], "findings_new": [], "metric_deltas": {},
        }

    def test_finding_gone_and_module_up_is_improved(self):
        before = make_report("a", osc_score=60.0, overall=70.0, findings=[osc_finding()])
        after = make_report("b", osc_score=95.0, overall=88.0)
        result = verify(before, after, {"MC_ROLLRATE_P"})
        assert result["status"] == "improved"
        assert result["next_report_id"] == "b"
        assert result["findings_resolved"] == ["Roll oscillation at 6.0 Hz"]
        assert result["findings_new"] == []
        assert result["metric_deltas"] == {"overall_score": 18.0, "module.oscillation": 35.0}

    def test_param_names_match_case_insensitively(self):
        before = make_report("a", findings=[osc_finding()])
        after = make_report("b")
        assert verify(before, after, {"mc_rollrate_p"})["status"] == "improved"

    def test_same_finding_kind_with_new_value_is_not_resolved(self):
        before = make_report("a", osc_score=60.0, findings=[osc_finding("Roll oscillation at 6.0 Hz")])
        after = make_report("b", osc_score=61.0, findings=[osc_finding("Roll oscillation at 5.1 Hz")])
        result = verify(before, after, {"MC_ROLLRATE_P"})
        assert result["findings_resolved"] == []
        assert result["findings_new"] == []
        assert result["status"] == "unchanged"

    def test_new_relevant_finding_is_worse(self):
        before = make_report("a", osc_score=90.0)
        after = make_report("b", osc_score=90.0, findings=[osc_finding()])
        result = verify(before, after, {"MC_ROLLRATE_P"})
        assert result["status"] == "worse"
        assert result["findings_new"] == ["Roll oscillation at 6.0 Hz"]

    def test_resolved_but_new_problem_is_mixed(self):
        pitch = osc_finding("Pitch oscillation at 4 Hz", kind="oscillation.pitch", params=("MC_PITCHRATE_P",))
        before = make_report("a", osc_score=70.0, findings=[osc_finding()])
        after = make_report("b", osc_score=70.0, findings=[pitch])
        result = verify(before, after, {"MC_ROLLRATE_P", "MC_PITCHRATE_P"})
        assert result["status"] == "mixed"

    def test_unrelated_findings_and_modules_are_ignored(self):
        before = make_report("a", osc_score=60.0, gps_score=100.0, findings=[osc_finding()])
        after = make_report("b", osc_score=95.0, gps_score=40.0, findings=[gps_finding()])
        result = verify(before, after, {"MC_ROLLRATE_P"})
        assert result["status"] == "improved"
        assert "module.gps" not in result["metric_deltas"]
        assert result["findings_new"] == []

    def test_small_score_wobble_is_unchanged(self):
        before = make_report("a", osc_score=80.0, overall=80.0)
        after = make_report("b", osc_score=81.0, overall=79.0)
        assert verify(before, after, {"MC_ROLLRATE_P"})["status"] == "unchanged"

    def test_older_reports_fall_back_to_param_recommendations(self):
        old_style = Finding(
            category=Category.OSCILLATION, severity=Severity.WARNING, title="Roll oscillation",
            technical_summary="t", plain_english="p", recommendation="r", confidence=0.9,
            param_changes=[ParamRecommendation(param_name="MC_ROLLRATE_D", current_value=0.003,
                                               suggested_value=0.002, change_direction="decrease",
                                               reason="r")],
        )
        before = make_report("a", findings=[old_style])
        after = make_report("b")
        assert verify(before, after, {"MC_ROLLRATE_D"})["findings_resolved"] == ["Roll oscillation"]


@pytest.fixture
def database(tmp_path, monkeypatch):
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


def claim(label="Quad-1"):
    from api import airframe_store as afs
    return {"X-Airframe-Token": afs.airframe_store.authorise(label, None, claim=True)}


def flight(report_id, label="Quad-1", sha=None, **kwargs):
    from api.storage import job_store
    job_store.create(report_id, airframe_label=label, log_sha256=sha)
    job_store.complete(report_id, make_report(report_id, **kwargs))


def backdate(database, table, key, value, seconds):
    database.execute(f"UPDATE {table} SET created_at = ? WHERE {key} = ?", (time.time() - seconds, value))


BODY = {
    "report_id": "before",
    "changes": [{"name": "MC_ROLLRATE_P", "from_value": 0.18, "to_value": 0.15}],
    "applied_by": "user",
    "note": "lowered roll P",
}


class TestChangesEndpoints:
    @pytest.mark.asyncio
    async def test_needs_the_airframe_token(self, client):
        auth = claim()
        flight("before")
        assert (await client.post("/airframe/Quad-1/changes", json=BODY)).status_code == 401
        resp = await client.post("/airframe/Quad-1/changes", json=BODY, headers={"X-Airframe-Token": "nope"})
        assert resp.status_code == 403
        assert (await client.get("/airframe/Quad-1/changes")).status_code == 401
        assert (await client.get("/airframe/Quad-1/changes", headers=auth)).status_code == 200

    @pytest.mark.asyncio
    async def test_unclaimed_airframe_is_refused(self, client):
        assert (await client.post("/airframe/Nobody/changes", json=BODY)).status_code == 401

    @pytest.mark.asyncio
    async def test_record_returns_201_and_pending(self, client):
        auth = claim()
        flight("before", osc_score=60.0, findings=[osc_finding()])

        resp = await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"]
        assert data["created_at"] > 0
        assert data["report_id"] == "before"
        assert data["changes"] == [{"name": "MC_ROLLRATE_P", "from_value": 0.18, "to_value": 0.15}]
        assert data["applied_by"] == "user"
        assert data["verify"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_report_of_another_airframe_is_refused(self, client):
        auth = claim()
        flight("before", label="Quad-2")
        resp = await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unfinished_or_unknown_report_is_refused(self, client):
        from api.storage import job_store
        auth = claim()
        job_store.create("running", airframe_label="Quad-1")
        for rid in ("running", "missing"):
            resp = await client.post("/airframe/Quad-1/changes", json={**BODY, "report_id": rid}, headers=auth)
            assert resp.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("change", [
        {"name": "MC ROLL; drop", "to_value": 1.0},
        {"name": "X" * 33, "to_value": 1.0},
        {"name": "MC_ROLLRATE_P"},
    ])
    async def test_bad_change_rows_are_422(self, client, change):
        auth = claim()
        flight("before")
        resp = await client.post("/airframe/Quad-1/changes", json={**BODY, "changes": [change]}, headers=auth)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_applied_by_is_user_or_uaop(self, client):
        auth = claim()
        flight("before")
        resp = await client.post("/airframe/Quad-1/changes", json={**BODY, "applied_by": "someone"}, headers=auth)
        assert resp.status_code == 422
        resp = await client.post("/airframe/Quad-1/changes", json={**BODY, "applied_by": "uaop"}, headers=auth)
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_next_flight_verifies_the_change(self, client, database):
        auth = claim()
        flight("before", osc_score=60.0, overall=70.0, findings=[osc_finding()])
        backdate(database, "reports", "report_id", "before", 600)
        change_id = (await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)).json()["id"]
        backdate(database, "param_changes", "id", change_id, 300)

        flight("after", osc_score=95.0, overall=90.0)
        flight("later", osc_score=50.0, overall=50.0, findings=[osc_finding()])

        resp = await client.get("/airframe/Quad-1/changes", headers=auth)
        assert resp.status_code == 200
        [item] = resp.json()
        assert item["id"] == change_id
        assert item["note"] == "lowered roll P"
        v = item["verify"]
        assert v["status"] == "improved"
        assert v["next_report_id"] == "after"
        assert v["findings_resolved"] == ["Roll oscillation at 6.0 Hz"]
        assert v["findings_new"] == []
        assert v["metric_deltas"]["module.oscillation"] == 35.0

    @pytest.mark.asyncio
    async def test_reupload_of_the_source_log_is_not_the_next_flight(self, client, database):
        auth = claim()
        flight("before", sha="a" * 64, findings=[osc_finding()])
        backdate(database, "reports", "report_id", "before", 600)
        change_id = (await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)).json()["id"]
        backdate(database, "param_changes", "id", change_id, 300)
        flight("same-log-again", sha="a" * 64, findings=[osc_finding()])

        [item] = (await client.get("/airframe/Quad-1/changes", headers=auth)).json()
        assert item["verify"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_is_newest_first(self, client, database):
        auth = claim()
        flight("before")
        first = (await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)).json()["id"]
        backdate(database, "param_changes", "id", first, 60)
        second = (await client.post("/airframe/Quad-1/changes", json=BODY, headers=auth)).json()["id"]

        ids = [c["id"] for c in (await client.get("/airframe/Quad-1/changes", headers=auth)).json()]
        assert ids == [second, first]


class TestRefreshPending:
    def test_stores_the_result_once_a_later_flight_lands(self, database):
        flight("before", osc_score=60.0, findings=[osc_finding()])
        backdate(database, "reports", "report_id", "before", 600)
        change = param_change_store.add("Quad-1", "before", BODY["changes"], "uaop")
        backdate(database, "param_changes", "id", change["id"], 300)

        assert refresh_pending("Quad-1") == 0
        flight("after", osc_score=95.0)
        assert refresh_pending("Quad-1") == 1

        row = database.query_one("SELECT verify_json FROM param_changes WHERE id = ?", (change["id"],))
        assert '"improved"' in row[0]
