"""
Export cache: built once per report id + schema version (+ app version),
served from disk afterwards, dropped with the report, and written atomically.
"""

import json
import os

import pytest

from api import db, export_cache, fs
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report(report_id="r1", schema_version=None):
    r = FlightMDReport(
        report_id=report_id, overall_score=85.0, score_label="Good", letter_grade="B",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=60.0),
        findings=[], param_change_sheet=[], analyser_results=[],
        processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
    )
    if schema_version:
        r.schema_version = schema_version
    return r


@pytest.fixture
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


def counting(payload=b"data"):
    calls = []

    def build(report):
        calls.append(report.report_id)
        return payload
    return build, calls


class TestExportCache:
    def test_built_once(self, database):
        build, calls = counting()
        report = make_report()
        assert export_cache.get_or_build(report, "report.pdf", build) == b"data"
        assert export_cache.get_or_build(report, "report.pdf", build) == b"data"
        assert calls == ["r1"]

    def test_kinds_and_reports_are_separate(self, database):
        build, calls = counting()
        export_cache.get_or_build(make_report("r1"), "track.gpx", build)
        export_cache.get_or_build(make_report("r1"), "track.kml", build)
        export_cache.get_or_build(make_report("r2"), "track.gpx", build)
        assert calls == ["r1", "r1", "r2"]

    def test_new_schema_version_rebuilds(self, database):
        build, calls = counting()
        export_cache.get_or_build(make_report(schema_version="1.7"), "report.json", build)
        export_cache.get_or_build(make_report(schema_version="1.8"), "report.json", build)
        assert len(calls) == 2

    def test_new_app_version_rebuilds(self, database, monkeypatch):
        from api.config import get_settings
        build, calls = counting()
        export_cache.get_or_build(make_report(), "report.pdf", build)
        monkeypatch.setattr(get_settings(), "app_version", "9.9.9")
        export_cache.get_or_build(make_report(), "report.pdf", build)
        assert len(calls) == 2

    def test_drop_removes_the_reports_exports(self, database):
        build, calls = counting()
        export_cache.get_or_build(make_report(), "report.pdf", build)
        export_cache.drop("r1")
        assert not os.path.exists(os.path.join(database.data_dir, "exports", "r1"))
        export_cache.get_or_build(make_report(), "report.pdf", build)
        assert len(calls) == 2

    def test_unwritable_cache_still_returns_the_export(self, database, monkeypatch):
        def broken(path, data):
            raise OSError("read-only fs")
        monkeypatch.setattr(export_cache, "write_atomic", broken)
        build, calls = counting()
        assert export_cache.get_or_build(make_report(), "report.pdf", build) == b"data"

    def test_odd_report_ids_never_reach_the_disk(self, database):
        build, _ = counting()
        with pytest.raises(ValueError):
            export_cache.get_or_build(make_report("../../etc"), "report.pdf", build)

    def test_expiry_sweep_drops_exports(self, database):
        import time
        import api.main as main
        from api.storage import job_store

        job_store.create("r1")
        job_store.complete("r1", make_report("r1"))
        export_cache.get_or_build(make_report("r1"), "report.pdf", lambda r: b"pdf")
        database.execute("UPDATE reports SET created_at = ? WHERE report_id = 'r1'", (time.time() - 7200,))

        main._sweep()

        assert job_store.get("r1") is None
        assert not os.path.exists(os.path.join(database.data_dir, "exports", "r1"))


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
