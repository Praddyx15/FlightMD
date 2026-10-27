"""
JobStore: airframe tagging, retention, eviction and safe writes.

Untagged reports must really expire after the TTL; tagged ones are kept for
trend history; a running job is never evicted; report files are replaced
atomically.
"""

import json
import os
import time

import pytest

from api import fs
from api.storage import JobStatus, JobStore, StoreFull, normalise_airframe_label
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
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path))
    return JobStore()


def age_report_file(store, report_id, seconds):
    path = os.path.join(store.DATA_DIR, f"{report_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["created_at"] = time.time() - seconds
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestAirframeLabelNormalisation:
    def test_none_stays_none(self):
        assert normalise_airframe_label(None) is None

    def test_empty_string_becomes_none(self):
        assert normalise_airframe_label("   ") is None

    def test_trims_whitespace(self):
        assert normalise_airframe_label("  Quad-1  ") == "Quad-1"

    def test_truncates_to_max_length(self):
        assert len(normalise_airframe_label("x" * 100)) == 40

    @pytest.mark.parametrize("label", ["Quad/1", "Quad\\1", "Quad\n1", "Quad\x001"])
    def test_unroutable_labels_rejected(self, label):
        assert normalise_airframe_label(label) is None

    def test_non_ascii_label_kept(self):
        assert normalise_airframe_label("Квадро-1") == "Квадро-1"


class TestJobLifecycle:
    def test_create_and_get(self, store):
        job = store.create("test-id-123")
        assert job.status == JobStatus.PROCESSING
        assert store.get("test-id-123").report_id == "test-id-123"

    def test_update_progress(self, store):
        store.create("test-id-456")
        store.update_progress("test-id-456", 50, "Halfway there")
        job = store.get("test-id-456")
        assert job.progress == 50
        assert job.message == "Halfway there"

    def test_fail(self, store):
        store.create("test-id-789")
        store.fail("test-id-789", "Parsing failed")
        job = store.get("test-id-789")
        assert job.status == JobStatus.FAILED
        assert job.error == "Parsing failed"

    def test_unknown_id_returns_none(self, store):
        assert store.get("does-not-exist") is None
        assert store.status_summary("ghost-id")["status"] == "not_found"

    def test_ids_that_look_like_paths_never_reach_the_disk(self, store, tmp_path):
        outside = tmp_path.parent / "outside.json"
        outside.write_text(make_report("outside").model_dump_json(), encoding="utf-8")
        try:
            assert store.get("../outside") is None
        finally:
            outside.unlink()


class TestEviction:
    def test_running_jobs_are_never_evicted(self, store):
        store.MAX_JOBS = 3
        for i in range(3):
            store.create(f"job-{i}")
        with pytest.raises(StoreFull):
            store.create("job-3")
        assert {f"job-{i}" for i in range(3)} <= set(store._store)

    def test_finished_job_makes_room(self, store):
        store.MAX_JOBS = 3
        store.create("old", airframe_label="Quad-1")
        store.complete("old", make_report("old"))
        store.create("running-1", airframe_label="Quad-1")
        store.create("running-2")

        store.create("new")
        assert "old" not in store._store
        assert store.get("running-1").status == JobStatus.PROCESSING
        # the evicted finished job still loads from disk with its tag
        assert store.get("old").airframe_label == "Quad-1"


class TestRetention:
    def test_untagged_report_persists_immediately_after_completion(self, store):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        assert store.get("r1") is not None

    def test_untagged_report_deleted_after_ttl(self, store):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        age_report_file(store, "r1", 7200)

        assert store.cleanup_expired_disk_reports(ttl_seconds=3600) == 1
        assert store.get("r1") is None

    def test_tagged_report_survives_cleanup_regardless_of_age(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        age_report_file(store, "r1", 999999)

        assert store.cleanup_expired_disk_reports(ttl_seconds=3600) == 0
        assert store.get("r1") is not None

    def test_legacy_unwrapped_report_file_still_loads(self, store):
        path = os.path.join(store.DATA_DIR, "legacy.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(make_report("legacy").model_dump_json())

        job = store.get("legacy")
        assert job is not None
        assert job.airframe_label is None
        assert job.report.report_id == "legacy"


class TestAtomicWrites:
    def test_failed_replace_keeps_the_old_file_and_leaves_no_temp(self, tmp_path, monkeypatch):
        path = str(tmp_path / "r.json")
        fs.write_json_atomic(path, {"v": 1})

        def broken_replace(src, dst):
            raise OSError("disk full")
        monkeypatch.setattr(fs.os, "replace", broken_replace)

        with pytest.raises(OSError):
            fs.write_json_atomic(path, {"v": 2})

        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"v": 1}
        assert os.listdir(tmp_path) == ["r.json"]

    def test_complete_writes_through_the_atomic_helper(self, store, monkeypatch):
        import api.storage as storage_module
        written = []
        monkeypatch.setattr(storage_module, "write_json_atomic", lambda path, obj: written.append(path))
        store.create("r1")
        store.complete("r1", make_report("r1"))
        assert written == [os.path.join(store.DATA_DIR, "r1.json")]


class TestAirframeTrends:
    def test_list_by_airframe_returns_only_matching_tagged_reports(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1", score=80.0))
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2", score=85.0))
        store.create("r3", airframe_label="Quad-2")
        store.complete("r3", make_report("r3", score=50.0))
        store.create("r4")
        store.complete("r4", make_report("r4", score=90.0))

        assert {r.report_id for r in store.list_by_airframe("Quad-1")} == {"r1", "r2"}

    def test_list_by_airframe_sorted_oldest_first(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        time.sleep(0.01)
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2"))

        assert [r.report_id for r in store.list_by_airframe("Quad-1")] == ["r1", "r2"]

    def test_unknown_airframe_returns_empty(self, store):
        assert store.list_by_airframe("Nonexistent") == []

    def test_global_listing_no_longer_exists(self, store):
        assert not hasattr(store, "get_all_reports")
