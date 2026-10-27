"""
The opt-in dataset store must never keep uploader-identifying data: no name,
IP, original filename, place name or GPS track. Only the log bytes and a
stripped report.
"""

import json

import pytest

from api.training_data_store import TrainingDataStore
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report() -> FlightMDReport:
    meta = FlightMetadata(
        duration_seconds=120.0,
        firmware_version="1.14.0",
        location_name="Smith Farm, Ruralshire",
        gps_path=[[12.3456789, -0.142, 10.0], [12.3456790, -0.143, 12.0]],
    )
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
    data = tmp_path / "data"
    monkeypatch.setattr(TrainingDataStore, "DATA_DIR", str(data))
    return TrainingDataStore()


@pytest.fixture
def log_file(tmp_path):
    def write(content=b"fake log bytes", name="upload.ulg"):
        path = tmp_path / name
        path.write_bytes(content)
        return str(path)
    return write


class TestSave:
    def test_returns_a_contribution_id(self, store, log_file):
        assert store.save(log_file(), ".ulg", "ulog", make_report())

    def test_writes_raw_log_and_metadata_files(self, store, log_file):
        contribution_id = store.save(log_file(), ".ulg", "ulog", make_report())
        data_dir = store.DATA_DIR
        with open(f"{data_dir}/{contribution_id}.ulg", "rb") as f:
            assert f.read() == b"fake log bytes"
        with open(f"{data_dir}/{contribution_id}.json", encoding="utf-8") as f:
            assert json.load(f)["log_format"] == "ulog"

    def test_metadata_excludes_uploader_identity(self, store, log_file):
        contribution_id = store.save(log_file(), ".ulg", "ulog", make_report())
        with open(f"{store.DATA_DIR}/{contribution_id}.json", encoding="utf-8") as f:
            raw = f.read()
        meta = json.loads(raw)

        assert set(meta.keys()) == {"contribution_id", "log_format", "contributed_at", "report"}
        assert "secret_uploader_filename" not in raw
        assert "Smith Farm" not in raw
        assert "12.3456789" not in raw
        assert meta["report"]["metadata"]["gps_path"] is None
        assert meta["report"]["metadata"]["location_name"] is None
        assert meta["report"]["report_id"] == ""

    def test_the_source_file_is_left_alone(self, store, log_file):
        path = log_file()
        store.save(path, ".ulg", "ulog", make_report())
        with open(path, "rb") as f:
            assert f.read() == b"fake log bytes"

    def test_different_logs_get_different_ids(self, store, log_file):
        id_a = store.save(log_file(b"a", "a.ulg"), ".ulg", "ulog", make_report())
        id_b = store.save(log_file(b"b", "b.ulg"), ".ulg", "ulog", make_report())
        assert id_a != id_b

    def test_same_log_twice_is_stored_once(self, store, log_file):
        id_a = store.save(log_file(b"same", "a.ulg"), ".ulg", "ulog", make_report())
        id_b = store.save(log_file(b"same", "b.ulg"), ".ulg", "ulog", make_report())
        assert id_a == id_b
        assert store.stats().count == 1


class TestStats:
    def test_empty_store_reports_zero(self, store):
        stats = store.stats()
        assert stats.count == 0
        assert stats.total_bytes == 0

    def test_counts_logs_not_metadata_files(self, store, log_file):
        store.save(log_file(b"12345", "a.ulg"), ".ulg", "ulog", make_report())
        store.save(log_file(b"1234567890", "b.bin"), ".bin", "ardupilot", make_report())
        stats = store.stats()
        assert stats.count == 2
        assert stats.total_bytes == 15
