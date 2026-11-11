"""
One-time import of the old JSON-file stores (api/data/{reports,airframes,
training_contributions}) into SQLite: everything readable comes across with
its tag, token hash and timestamps, the old directories are renamed rather
than deleted, and a second start imports nothing.
"""

import json
import os

import pytest

from api import db
from api.airframe_store import AirframeConfigStore, hash_token
from api.legacy_import import import_legacy
from api.storage import JobStatus, JobStore
from api.training_data_store import TrainingDataStore
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def report_dict(report_id="r1", score=85.0):
    return FlightMDReport(
        report_id=report_id, overall_score=score, score_label="Good", letter_grade="B",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=60.0),
        findings=[], param_change_sheet=[], analyser_results=[],
        processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
    ).model_dump(mode="json")


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest.fixture
def legacy(tmp_path):
    root = tmp_path / "old"
    write(root / "reports" / "tagged.json",
          {"airframe_label": "Quad-1", "created_at": 1_700_000_000.0, "report": report_dict("tagged", 70.0)})
    write(root / "reports" / "untagged.json",
          {"airframe_label": None, "created_at": 1_700_000_100.0, "report": report_dict("untagged")})
    # pre-tagging files were a bare report dump
    write(root / "reports" / "bare.json", report_dict("bare"))
    (root / "reports" / "broken.json").write_text("{nope", encoding="utf-8")

    write(root / "airframes" / "Quad_1-0123456789abcdef.json", {
        "airframe_label": "Quad-1", "checklist_items": ["props"], "token_hash": hash_token("secret-token"),
        "maintenance_log": [{"date": "2026-01-01", "maintenance_type": "Props", "notes": ""}],
    })
    # an older slug-named copy of the same airframe must not win
    write(root / "airframes" / "Quad_1.json", {"airframe_label": "Quad-1", "checklist_items": ["stale"]})

    cid = "ab" * 16
    (root / "training_contributions").mkdir()
    (root / "training_contributions" / f"{cid}.bin").write_bytes(b"old contributed log")
    write(root / "training_contributions" / f"{cid}.json", {
        "contribution_id": cid, "log_format": "ardupilot_bin", "contributed_at": 1_700_000_200.0,
        "report": report_dict(""),
    })
    return root


class TestImport:
    def test_reports_come_across_with_tag_and_time(self, database, legacy):
        counts = import_legacy([str(legacy)])
        assert counts == {"reports": 3, "airframes": 1, "contributions": 1}

        jobs = JobStore()
        tagged = jobs.get("tagged")
        assert tagged.status == JobStatus.COMPLETE
        assert tagged.airframe_label == "Quad-1"
        assert tagged.created_at == 1_700_000_000.0
        assert tagged.report.overall_score == 70.0
        assert jobs.get("untagged").airframe_label is None
        assert jobs.get("bare").report.report_id == "bare"
        assert jobs.get("broken") is None

    def test_airframe_keeps_its_token_and_log(self, database, legacy):
        import_legacy([str(legacy)])
        store = AirframeConfigStore()
        config = store.get("Quad-1")
        assert config.checklist_items == ["props"]
        assert [m.maintenance_type for m in config.maintenance_log] == ["Props"]
        assert store.authorise("Quad-1", "secret-token") is None

    def test_contribution_moves_into_the_blob_store(self, database, legacy):
        import_legacy([str(legacy)])
        assert TrainingDataStore().stats().count == 1
        with open(os.path.join(database.data_dir, "blobs", f"{'ab' * 16}.bin"), "rb") as f:
            assert f.read() == b"old contributed log"

    def test_old_directories_are_renamed_not_deleted(self, database, legacy):
        import_legacy([str(legacy)])
        assert not (legacy / "reports").exists()
        assert (legacy / "reports.imported" / "tagged.json").exists()
        # the unreadable file is still there for the owner to look at
        assert (legacy / "reports.imported" / "broken.json").exists()
        assert (legacy / "airframes.imported").is_dir()
        assert (legacy / "training_contributions.imported").is_dir()

    def test_second_start_imports_nothing(self, database, legacy):
        import_legacy([str(legacy)])
        assert import_legacy([str(legacy)]) == {"reports": 0, "airframes": 0, "contributions": 0}

    def test_existing_rows_are_not_overwritten(self, database, legacy):
        jobs = JobStore()
        jobs.create("tagged", airframe_label="Other")
        import_legacy([str(legacy)])
        assert jobs.get("tagged").airframe_label == "Other"

    def test_same_root_listed_twice_is_imported_once(self, database, legacy):
        counts = import_legacy([str(legacy), str(legacy) + os.sep])
        assert counts["reports"] == 3

    def test_missing_root_is_fine(self, database, tmp_path):
        assert import_legacy([str(tmp_path / "never-existed")]) == {"reports": 0, "airframes": 0, "contributions": 0}
