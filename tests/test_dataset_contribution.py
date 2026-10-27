"""
contribute_to_dataset wiring in _run_analysis_task: the flag gates the save, a
failed save never fails the job, and the uploaded temp file is always removed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.routers.analyse as analyse_module
from api.storage import JobStatus, JobStore
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
def patch_run_analysis(monkeypatch, tmp_path):
    async def fake_run_analysis(**kwargs):
        return make_report()
    monkeypatch.setattr(analyse_module, "run_analysis", fake_run_analysis)
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(analyse_module.job_store, "_store", {})


@pytest.fixture
def log_path(tmp_path):
    path = tmp_path / "upload.ulg"
    path.write_bytes(b"fake bytes")
    return str(path)


async def run(log_path, contribute):
    await analyse_module._run_analysis_task(
        report_id="r1", log_path=log_path, file_name="f.ulg",
        file_size=10, log_format="px4_ulog", contribute_to_dataset=contribute,
    )


class TestContributeToDatasetWiring:
    @pytest.mark.asyncio
    async def test_opted_in_saves_to_training_store(self, monkeypatch, log_path):
        calls = []

        def fake_save(path, suffix, log_format, report):
            with open(path, "rb") as f:
                calls.append((f.read(), suffix, log_format))
            return "contribution-id"
        monkeypatch.setattr(analyse_module.training_data_store, "save", fake_save)

        await run(log_path, contribute=True)

        assert calls == [(b"fake bytes", ".ulg", "px4_ulog")]

    @pytest.mark.asyncio
    async def test_opted_out_does_not_save(self, monkeypatch, log_path):
        calls = []
        monkeypatch.setattr(analyse_module.training_data_store, "save", lambda *a: calls.append(a))

        await run(log_path, contribute=False)

        assert calls == []

    @pytest.mark.asyncio
    async def test_save_failure_does_not_fail_the_job(self, monkeypatch, log_path):
        def boom(*a):
            raise RuntimeError("disk full")
        monkeypatch.setattr(analyse_module.training_data_store, "save", boom)
        analyse_module.job_store.create("r1")

        await run(log_path, contribute=True)

        assert analyse_module.job_store.get("r1").status == JobStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_temp_file_removed_after_success_and_failure(self, monkeypatch, log_path, tmp_path):
        monkeypatch.setattr(analyse_module.training_data_store, "save", lambda *a: "id")
        await run(log_path, contribute=True)
        assert not os.path.exists(log_path)

        second = tmp_path / "second.ulg"
        second.write_bytes(b"x")

        async def failing_run_analysis(**kwargs):
            raise ValueError("no analysable telemetry")
        monkeypatch.setattr(analyse_module, "run_analysis", failing_run_analysis)
        await run(str(second), contribute=False)
        assert not second.exists()
