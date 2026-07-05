"""
Tests for JobStore — airframe tagging and retention enforcement.

Untagged reports must actually expire (the README advertises "reports
expire after 1 hour" — this used to not be true for completed jobs, since
they were written to disk with no cleanup at all). Tagged reports must be
kept indefinitely so cross-flight trend analysis has history to read.
"""

import time

import pytest

from api.storage import JobStore, normalise_airframe_label
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report(report_id: str = "test-id", score: float = 85.0) -> FlightMDReport:
    meta = FlightMetadata(duration_seconds=120.0, firmware_version="1.14.0")
    return FlightMDReport(
        report_id=report_id,
        overall_score=score,
        score_label="Good",
        letter_grade="B",
        executive_summary="Summary",
        metadata=meta,
        findings=[],
        param_change_sheet=[],
        analyser_results=[],
        processing_time_ms=10,
        file_name="test.ulg",
        file_size_bytes=1024,
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = JobStore.__new__(JobStore)
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path))
    s.__init__()
    return s


class TestAirframeLabelNormalisation:
    def test_none_stays_none(self):
        assert normalise_airframe_label(None) is None

    def test_empty_string_becomes_none(self):
        assert normalise_airframe_label("   ") is None

    def test_trims_whitespace(self):
        assert normalise_airframe_label("  Quad-1  ") == "Quad-1"

    def test_truncates_to_max_length(self):
        long_label = "x" * 100
        assert len(normalise_airframe_label(long_label)) == 40


class TestRetention:
    def test_untagged_report_persists_immediately_after_completion(self, store):
        job = store.create("r1")
        store.complete("r1", make_report("r1"))
        assert store.get("r1") is not None

    def test_untagged_report_deleted_after_ttl(self, store):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        # Simulate time passing by rewriting created_at in the persisted file.
        import json, os
        path = os.path.join(store.DATA_DIR, "r1.json")
        with open(path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            data["created_at"] = time.time() - 7200  # 2 hours ago
            f.seek(0)
            json.dump(data, f)
            f.truncate()

        deleted = store.cleanup_expired_disk_reports(ttl_seconds=3600)
        assert deleted == 1
        assert store.get("r1") is None

    def test_tagged_report_survives_cleanup_regardless_of_age(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        import json, os
        path = os.path.join(store.DATA_DIR, "r1.json")
        with open(path, "r+", encoding="utf-8") as f:
            data = json.load(f)
            data["created_at"] = time.time() - 999999  # long expired if it were untagged
            f.seek(0)
            json.dump(data, f)
            f.truncate()

        deleted = store.cleanup_expired_disk_reports(ttl_seconds=3600)
        assert deleted == 0
        assert store.get("r1") is not None

    def test_legacy_unwrapped_report_file_still_loads(self, store):
        """Reports persisted before airframe tagging shipped have no
        wrapper — just a raw FlightMDReport dump. These must still load,
        treated as untagged."""
        import json, os
        path = os.path.join(store.DATA_DIR, "legacy.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(make_report("legacy").model_dump_json())

        job = store.get("legacy")
        assert job is not None
        assert job.airframe_label is None
        assert job.report.report_id == "legacy"


class TestAirframeTrends:
    def test_list_by_airframe_returns_only_matching_tagged_reports(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1", score=80.0))
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2", score=85.0))
        store.create("r3", airframe_label="Quad-2")
        store.complete("r3", make_report("r3", score=50.0))
        store.create("r4")  # untagged
        store.complete("r4", make_report("r4", score=90.0))

        reports = store.list_by_airframe("Quad-1")
        assert {r.report_id for r in reports} == {"r1", "r2"}

    def test_list_by_airframe_sorted_oldest_first(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        time.sleep(0.01)
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2"))

        reports = store.list_by_airframe("Quad-1")
        assert [r.report_id for r in reports] == ["r1", "r2"]

    def test_unknown_airframe_returns_empty(self, store):
        assert store.list_by_airframe("Nonexistent") == []


class TestReportSummaries:
    def test_get_all_reports_includes_airframe_label(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        store.create("r2")
        store.complete("r2", make_report("r2"))

        summaries = {s["report_id"]: s for s in store.get_all_reports()}
        assert summaries["r1"]["airframe_label"] == "Quad-1"
        assert summaries["r2"]["airframe_label"] is None
