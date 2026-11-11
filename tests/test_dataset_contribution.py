"""
contribute_to_dataset wiring in run_job: the flag gates the save, a failed
save never fails the job, and the uploaded file is always removed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.analysis as analysis_module
from api import db
from api.analysis import AnalysisJob, run_job
from api.storage import JobStatus, job_store
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


def make_report() -> FlightMDReport:
    return FlightMDReport(
        report_id="r1", overall_score=85.0, score_label="Good", letter_grade="B",
        executive_summary="s", metadata=FlightMetadata(duration_seconds=60.0),
        findings=[], param_change_sheet=[], analyser_results=[],
        processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
    )


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    async def fake_run_analysis(**kwargs):
        return make_report()
    monkeypatch.setattr(analysis_module, "run_analysis", fake_run_analysis)

    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


@pytest.fixture
def log_path(tmp_path):
    path = tmp_path / "upload.ulg"
    path.write_bytes(b"fake bytes")
    return str(path)


async def run(log_path, contribute):
    job_store.create("r1", log_sha256="d" * 64)
    await run_job(AnalysisJob(
        report_id="r1", log_path=log_path, file_name="f.ulg",
        file_size=10, log_format="px4_ulog", contribute_to_dataset=contribute,
        log_sha256="d" * 64,
    ))


class TestContributeToDatasetWiring:
    @pytest.mark.asyncio
    async def test_opted_in_saves_to_training_store(self, monkeypatch, log_path):
        calls = []

        def fake_save(path, suffix, log_format, report, log_sha256):
            with open(path, "rb") as f:
                calls.append((f.read(), suffix, log_format, log_sha256))
            return "contribution-id"
        monkeypatch.setattr(analysis_module.training_data_store, "save", fake_save)

        await run(log_path, contribute=True)

        assert calls == [(b"fake bytes", ".ulg", "px4_ulog", "d" * 64)]

    @pytest.mark.asyncio
    async def test_opted_in_really_stores_it(self, log_path):
        from api.training_data_store import training_data_store
        await run(log_path, contribute=True)
        assert training_data_store.stats().count == 1

    @pytest.mark.asyncio
    async def test_opted_out_does_not_save(self, monkeypatch, log_path):
        calls = []
        monkeypatch.setattr(analysis_module.training_data_store, "save", lambda *a: calls.append(a))

        await run(log_path, contribute=False)

        assert calls == []

    @pytest.mark.asyncio
    async def test_save_failure_does_not_fail_the_job(self, monkeypatch, log_path):
        def boom(*a):
            raise RuntimeError("disk full")
        monkeypatch.setattr(analysis_module.training_data_store, "save", boom)

        await run(log_path, contribute=True)

        assert job_store.get("r1").status == JobStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_temp_file_removed_after_success_and_failure(self, monkeypatch, log_path, tmp_path):
        monkeypatch.setattr(analysis_module.training_data_store, "save", lambda *a: "id")
        await run(log_path, contribute=True)
        assert not os.path.exists(log_path)

        second = tmp_path / "second.ulg"
        second.write_bytes(b"x")

        async def failing_run_analysis(**kwargs):
            raise ValueError("no analysable telemetry")
        monkeypatch.setattr(analysis_module, "run_analysis", failing_run_analysis)
        job_store.discard("r1")
        await run(str(second), contribute=False)
        assert not second.exists()
        assert job_store.get("r1").status == JobStatus.FAILED
