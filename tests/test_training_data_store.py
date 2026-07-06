"""
Tests for the opt-in dataset-contribution store — must never persist
uploader-identifying data (name, IP, original filename), only the log
bytes and the report generated from it.
"""

import json

import pytest

from api.training_data_store import TrainingDataStore
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report() -> FlightMDReport:
    meta = FlightMetadata(duration_seconds=120.0, firmware_version="1.14.0")
    return FlightMDReport(
        report_id="test-id",
        overall_score=85.0,
        score_label="Good",
        letter_grade="B",
        executive_summary="Summary",
        metadata=meta,
        findings=[],
        param_change_sheet=[],
        analyser_results=[],
        processing_time_ms=10,
        file_name="secret_uploader_filename.ulg",
        file_size_bytes=1024,
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = TrainingDataStore.__new__(TrainingDataStore)
    monkeypatch.setattr(TrainingDataStore, "DATA_DIR", str(tmp_path))
    s.__init__()
    return s


class TestSave:
    def test_returns_a_contribution_id(self, store):
        contribution_id = store.save(b"fake log bytes", ".ulg", "ulog", make_report())
        assert contribution_id

    def test_writes_raw_log_and_metadata_files(self, store, tmp_path):
        contribution_id = store.save(b"fake log bytes", ".ulg", "ulog", make_report())
        assert (tmp_path / f"{contribution_id}.ulg").read_bytes() == b"fake log bytes"
        assert (tmp_path / f"{contribution_id}.json").exists()

    def test_metadata_excludes_uploader_identity(self, store, tmp_path):
        contribution_id = store.save(b"fake log bytes", ".ulg", "ulog", make_report())
        meta = json.loads((tmp_path / f"{contribution_id}.json").read_text(encoding="utf-8"))
        assert set(meta.keys()) == {"contribution_id", "log_format", "contributed_at", "report"}
        assert "uploader" not in meta
        assert "ip" not in meta
        assert "original_filename" not in meta

    def test_contribution_ids_are_unique(self, store):
        id_a = store.save(b"a", ".ulg", "ulog", make_report())
        id_b = store.save(b"b", ".ulg", "ulog", make_report())
        assert id_a != id_b


class TestStats:
    def test_empty_store_reports_zero(self, store):
        stats = store.stats()
        assert stats.count == 0
        assert stats.total_bytes == 0

    def test_counts_logs_not_metadata_files(self, store):
        store.save(b"12345", ".ulg", "ulog", make_report())
        store.save(b"1234567890", ".bin", "ardupilot", make_report())
        stats = store.stats()
        assert stats.count == 2
        assert stats.total_bytes == 15
