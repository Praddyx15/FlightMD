"""
The opt-in dataset store must never keep uploader-identifying data: no name,
IP, original filename, place name or GPS track. Only the log bytes (in the blob
store) and a stripped report (in the database). Withdrawal removes both.
"""

import hashlib
import json
import os
import sys
import types

import pytest

from api import blobs, db
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
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest.fixture
def store(database):
    return TrainingDataStore()


@pytest.fixture
def log_file(tmp_path):
    def write(content=b"fake log bytes", name="upload.ulg"):
        path = tmp_path / name
        path.write_bytes(content)
        return str(path)
    return write


def blob_dir(database):
    return os.path.join(database.data_dir, "blobs")


class TestSave:
    def test_id_is_the_content_hash_prefix(self, store, log_file):
        cid = store.save(log_file(), ".ulg", "px4_ulog", make_report())
        assert cid == hashlib.sha256(b"fake log bytes").hexdigest()[:32]

    def test_a_given_hash_is_used_as_is(self, store, log_file):
        assert store.save(log_file(), ".ulg", "px4_ulog", make_report(), "f" * 64) == "f" * 32

    def test_writes_raw_log_blob_and_row(self, store, log_file, database):
        cid = store.save(log_file(), ".ulg", "px4_ulog", make_report())
        with open(os.path.join(blob_dir(database), f"{cid}.ulg"), "rb") as f:
            assert f.read() == b"fake log bytes"
        row = database.query_one("SELECT log_format, size_bytes FROM contributions WHERE contribution_id = ?", (cid,))
        assert row["log_format"] == "px4_ulog"
        assert row["size_bytes"] == len(b"fake log bytes")

    def test_stored_report_excludes_uploader_identity(self, store, log_file, database):
        cid = store.save(log_file(), ".ulg", "px4_ulog", make_report())
        raw = database.query_one("SELECT report_json FROM contributions WHERE contribution_id = ?", (cid,))[0]
        report = json.loads(raw)

        assert "secret_uploader_filename" not in raw
        assert "Smith Farm" not in raw
        assert "12.3456789" not in raw
        assert report["file_name"] == ""
        assert report["metadata"]["gps_path"] is None
        assert report["metadata"]["location_name"] is None
        assert report["report_id"] == ""

    def test_the_source_file_is_left_alone(self, store, log_file):
        path = log_file()
        store.save(path, ".ulg", "px4_ulog", make_report())
        with open(path, "rb") as f:
            assert f.read() == b"fake log bytes"

    def test_different_logs_get_different_ids(self, store, log_file):
        id_a = store.save(log_file(b"a", "a.ulg"), ".ulg", "px4_ulog", make_report())
        id_b = store.save(log_file(b"b", "b.ulg"), ".ulg", "px4_ulog", make_report())
        assert id_a != id_b

    def test_same_log_twice_is_stored_once(self, store, log_file):
        id_a = store.save(log_file(b"same", "a.ulg"), ".ulg", "px4_ulog", make_report())
        id_b = store.save(log_file(b"same", "b.ulg"), ".ulg", "px4_ulog", make_report())
        assert id_a == id_b
        assert store.stats().count == 1

    def test_failed_blob_write_leaves_no_row(self, store, log_file, database, monkeypatch):
        class Broken:
            def put(self, key, src):
                raise OSError("disk full")
        monkeypatch.setattr(blobs, "get", lambda: Broken())

        with pytest.raises(OSError):
            store.save(log_file(), ".ulg", "px4_ulog", make_report())
        assert store.stats().count == 0


class TestDelete:
    def test_removes_blob_and_row(self, store, log_file, database):
        cid = store.save(log_file(), ".ulg", "px4_ulog", make_report())
        assert store.delete(cid) is True
        assert store.stats().count == 0
        assert os.listdir(blob_dir(database)) == []

    def test_unknown_id(self, store):
        assert store.delete("0" * 32) is False

    def test_failed_blob_delete_keeps_the_row(self, store, log_file, monkeypatch):
        cid = store.save(log_file(), ".ulg", "px4_ulog", make_report())

        class Broken:
            def delete(self, key):
                raise OSError("bucket unreachable")
        monkeypatch.setattr(blobs, "get", lambda: Broken())

        with pytest.raises(OSError):
            store.delete(cid)
        assert store.stats().count == 1


class TestStats:
    def test_empty_store_reports_zero(self, store):
        stats = store.stats()
        assert stats.count == 0
        assert stats.total_bytes == 0

    def test_counts_logs_and_bytes(self, store, log_file):
        store.save(log_file(b"12345", "a.ulg"), ".ulg", "px4_ulog", make_report())
        store.save(log_file(b"1234567890", "b.bin"), ".bin", "ardupilot_bin", make_report())
        stats = store.stats()
        assert stats.count == 2
        assert stats.total_bytes == 15


class TestBlobStores:
    def test_local_keys_cannot_leave_the_directory(self, tmp_path):
        store = blobs.LocalBlobStore(str(tmp_path))
        for key in ("../x", "a/b", "..", "", ".hidden"):
            with pytest.raises(ValueError):
                store.exists(key)

    def test_local_put_exists_delete(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"abc")
        store = blobs.LocalBlobStore(str(tmp_path / "blobs"))
        store.put("k.bin", str(src))
        assert store.exists("k.bin")
        store.delete("k.bin")
        store.delete("k.bin")
        assert not store.exists("k.bin")

    def test_s3_is_used_when_a_bucket_is_set(self, monkeypatch, tmp_path):
        calls = []

        class FakeClient:
            def upload_file(self, src, bucket, key):
                calls.append(("put", bucket, key))

            def delete_object(self, Bucket, Key):
                calls.append(("delete", Bucket, Key))

        fake_boto3 = types.SimpleNamespace(client=lambda service, **kw: calls.append(("client", service, kw)) or FakeClient())
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

        from api.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "flightmd_s3_bucket", "logs")
        monkeypatch.setattr(settings, "flightmd_s3_prefix", "contrib/")
        monkeypatch.setattr(settings, "flightmd_s3_endpoint_url", "https://s3.example.com")
        monkeypatch.setattr(blobs, "_s3", None)

        store = blobs.get()
        store.put("abc.ulg", str(tmp_path / "unused"))
        store.delete("abc.ulg")

        assert calls[0] == ("client", "s3", {"endpoint_url": "https://s3.example.com", "region_name": None})
        assert calls[1:] == [("put", "logs", "contrib/abc.ulg"), ("delete", "logs", "contrib/abc.ulg")]

    def test_s3_without_boto3_says_what_to_install(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "boto3", None)
        with pytest.raises(RuntimeError, match=r"flightmd-core\[s3\]"):
            blobs.S3BlobStore("logs")
