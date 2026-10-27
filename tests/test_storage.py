"""
JobStore on SQLite: airframe tagging, retention, restart semantics, the
running-job cap, duplicate uploads, and the database's migrations.
"""

import sqlite3
import time

import pytest

from api import db
from api.storage import INTERRUPTED, JobStatus, JobStore, StoreFull, normalise_airframe_label
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_report(report_id: str = "test-id", score: float = 85.0, duration: float = 120.0) -> FlightMDReport:
    meta = FlightMetadata(duration_seconds=duration, firmware_version="1.14.0")
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
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest.fixture
def store(database):
    return JobStore()


def age(database, report_id, seconds):
    database.execute(
        "UPDATE reports SET created_at = ?, updated_at = ? WHERE report_id = ?",
        (time.time() - seconds, time.time() - seconds, report_id),
    )


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


class TestDatabase:
    def test_migrations_are_recorded_once(self, tmp_path):
        first = db.Database(str(tmp_path))
        first.close()
        again = db.Database(str(tmp_path))
        versions = [r[0] for r in again.query("SELECT version FROM schema_migrations")]
        again.close()
        assert versions == [v for v, _ in db.MIGRATIONS]

    def test_wal_mode(self, database):
        assert database.query_one("PRAGMA journal_mode")[0].lower() == "wal"

    def test_failed_transaction_rolls_back(self, store, database):
        store.create("r1")
        with pytest.raises(RuntimeError):
            with database.transaction() as c:
                c.execute("DELETE FROM reports WHERE report_id = ?", ("r1",))
                raise RuntimeError("boom")
        assert store.get("r1") is not None


class TestJobLifecycle:
    def test_create_and_get(self, store):
        job = store.create("test-id-123")
        assert job.status == JobStatus.PROCESSING
        assert store.get("test-id-123").report_id == "test-id-123"

    def test_update_progress_with_eta(self, store):
        store.create("test-id-456")
        store.update_progress("test-id-456", 50, "Halfway there", 30.0)
        summary = store.status_summary("test-id-456")
        assert summary["progress"] == 50
        assert summary["message"] == "Halfway there"
        assert 0 < summary["eta_seconds"] <= 30.0

    def test_eta_is_null_when_unknown(self, store):
        store.create("r1")
        store.update_progress("r1", 10, "Parsing")
        assert store.status_summary("r1")["eta_seconds"] is None

    def test_fail(self, store):
        store.create("test-id-789")
        store.fail("test-id-789", "Parsing failed")
        job = store.get("test-id-789")
        assert job.status == JobStatus.FAILED
        assert job.error == "Parsing failed"
        assert store.status_summary("test-id-789")["error"] == "Parsing failed"

    def test_complete_stores_the_report(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1", score=72.0))
        job = store.get("r1")
        assert job.status == JobStatus.COMPLETE
        assert job.report.overall_score == 72.0
        assert job.airframe_label == "Quad-1"

    def test_progress_after_completion_is_ignored(self, store):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        store.update_progress("r1", 10, "late callback")
        assert store.status_summary("r1")["progress"] == 100

    def test_unknown_id_returns_none(self, store):
        assert store.get("does-not-exist") is None
        assert store.status_summary("ghost-id")["status"] == "not_found"

    @pytest.mark.parametrize("report_id", ["../outside", "a b", "x" * 65])
    def test_odd_ids_are_never_looked_up(self, store, report_id):
        assert store.get(report_id) is None
        assert store.status_summary(report_id)["status"] == "not_found"

    def test_discard(self, store):
        store.create("r1")
        store.discard("r1")
        assert store.get("r1") is None


class TestRestart:
    def test_status_survives_a_new_store_and_connection(self, store, database, monkeypatch):
        store.create("done")
        store.complete("done", make_report("done"))
        store.create("running")
        database.close()

        reopened = db.Database(database.data_dir)
        monkeypatch.setattr(db, "_db", reopened)
        try:
            fresh = JobStore()
            assert fresh.status_summary("done")["status"] == "complete"
            assert fresh.status_summary("running")["status"] == "processing"
        finally:
            reopened.close()

    def test_running_jobs_become_failed_interrupted(self, store):
        store.create("running")
        store.update_progress("running", 40, "Analysing", 12.0)
        store.create("done")
        store.complete("done", make_report("done"))

        assert store.interrupt_running() == 1

        summary = store.status_summary("running")
        assert summary["status"] == "failed"
        assert summary["error"] == INTERRUPTED
        assert summary["error"].startswith("interrupted")
        assert summary["eta_seconds"] is None
        assert store.status_summary("done")["status"] == "complete"

    def test_stale_jobs_fail_but_active_ones_dont(self, store, database):
        store.create("stuck")
        store.create("busy")
        age(database, "stuck", 7200)

        assert store.fail_stale(3600) == 1
        assert store.get("stuck").status == JobStatus.FAILED
        assert store.get("busy").status == JobStatus.PROCESSING


class TestCapacity:
    def test_running_jobs_are_capped(self, store):
        store.MAX_JOBS = 3
        for i in range(3):
            store.create(f"job-{i}")
        with pytest.raises(StoreFull):
            store.create("job-3")

    def test_finished_jobs_do_not_count(self, store):
        store.MAX_JOBS = 2
        store.create("a")
        store.complete("a", make_report("a"))
        store.create("b")
        store.create("c")
        assert store.job_count == 2


class TestRetention:
    def test_untagged_report_deleted_after_ttl(self, store, database):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        age(database, "r1", 7200)

        assert store.cleanup_expired(3600) == ["r1"]
        assert store.get("r1") is None

    def test_fresh_untagged_report_kept(self, store):
        store.create("r1")
        store.complete("r1", make_report("r1"))
        assert store.cleanup_expired(3600) == []
        assert store.get("r1") is not None

    def test_tagged_report_survives_cleanup_regardless_of_age(self, store, database):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        age(database, "r1", 999999)

        assert store.cleanup_expired(3600) == []
        assert store.get("r1") is not None

    def test_old_failed_jobs_are_cleaned_even_when_tagged(self, store, database):
        store.create("r1", airframe_label="Quad-1")
        store.fail("r1", "bad log")
        age(database, "r1", 7200)
        assert store.cleanup_expired(3600) == ["r1"]

    def test_running_jobs_are_not_cleaned(self, store, database):
        store.create("r1")
        age(database, "r1", 7200)
        assert store.cleanup_expired(3600) == []


class TestDuplicates:
    def test_same_bytes_same_tag_within_ttl_is_found(self, store):
        store.create("r1", airframe_label="Quad-1", log_sha256=SHA_A)
        store.complete("r1", make_report("r1"))
        assert store.find_recent_duplicate(SHA_A, "Quad-1", None) == ("r1", "complete")

    def test_running_original_is_found_too(self, store):
        store.create("r1", log_sha256=SHA_A)
        assert store.find_recent_duplicate(SHA_A, None, None) == ("r1", "processing")

    def test_different_tag_or_brief_is_not_a_duplicate(self, store):
        store.create("r1", airframe_label="Quad-1", log_sha256=SHA_A)
        assert store.find_recent_duplicate(SHA_A, None, None) is None
        assert store.find_recent_duplicate(SHA_A, "Quad-2", None) is None
        assert store.find_recent_duplicate(SHA_A, "Quad-1", "c" * 64) is None

    def test_failed_or_old_original_is_not_reused(self, store, database):
        store.create("failed", log_sha256=SHA_A)
        store.fail("failed", "internal error")
        store.create("old", log_sha256=SHA_B)
        age(database, "old", 7200)
        assert store.find_recent_duplicate(SHA_A, None, None) is None
        assert store.find_recent_duplicate(SHA_B, None, None, max_age_s=3600) is None


class TestAirframeTrends:
    def test_list_by_airframe_returns_only_matching_finished_reports(self, store):
        for rid, label in (("r1", "Quad-1"), ("r2", "Quad-1"), ("r3", "Quad-2"), ("r4", None)):
            store.create(rid, airframe_label=label)
            store.complete(rid, make_report(rid))
        store.create("running", airframe_label="Quad-1")

        assert {r.report_id for r in store.list_by_airframe("Quad-1")} == {"r1", "r2"}

    def test_list_by_airframe_sorted_oldest_first(self, store, database):
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2"))
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        age(database, "r1", 100)

        assert [r.report_id for r in store.list_by_airframe("Quad-1")] == ["r1", "r2"]

    def test_same_log_uploaded_twice_counts_once(self, store, database):
        store.create("first", airframe_label="Quad-1", log_sha256=SHA_A)
        store.complete("first", make_report("first"))
        age(database, "first", 50)
        store.create("again", airframe_label="Quad-1", log_sha256=SHA_A)
        store.complete("again", make_report("again"))
        store.create("other", airframe_label="Quad-1", log_sha256=SHA_B)
        store.complete("other", make_report("other"))

        ids = [r.report_id for r in store.list_by_airframe("Quad-1")]
        assert ids[0] == "first"
        assert sorted(ids) == ["first", "other"]

    def test_reports_without_a_hash_are_never_merged(self, store):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2"))
        assert len(store.list_by_airframe("Quad-1")) == 2

    def test_unknown_airframe_returns_empty(self, store):
        assert store.list_by_airframe("Nonexistent") == []

    def test_unreadable_row_is_skipped(self, store, database):
        store.create("r1", airframe_label="Quad-1")
        store.complete("r1", make_report("r1"))
        store.create("r2", airframe_label="Quad-1")
        store.complete("r2", make_report("r2"))
        database.execute("UPDATE reports SET report_json = '{broken' WHERE report_id = 'r2'")
        store._parsed.clear()
        assert [r.report_id for r in store.list_by_airframe("Quad-1")] == ["r1"]


def test_database_file_is_plain_sqlite(database):
    c = sqlite3.connect(database.path)
    try:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        c.close()
    assert {"reports", "airframes", "contributions", "param_changes", "schema_migrations"} <= tables
