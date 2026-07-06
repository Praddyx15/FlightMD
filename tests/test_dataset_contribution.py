"""
Tests for the contribute_to_dataset wiring in _run_analysis_task — verifies
the opt-in flag actually gates the save, and that a save failure never
breaks the analysis job the uploader is waiting on.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.routers.analyse as analyse_module
from api.storage import JobStore
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
    # _run_analysis_task always completes the job, which always persists to
    # disk — redirect that away from the real api/data/reports/ directory.
    monkeypatch.setattr(JobStore, "DATA_DIR", str(tmp_path))


class TestContributeToDatasetWiring:
    @pytest.mark.asyncio
    async def test_opted_in_saves_to_training_store(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            analyse_module.training_data_store, "save",
            lambda *a: calls.append(a) or "contribution-id"
        )

        await analyse_module._run_analysis_task(
            report_id="r1", content=b"fake bytes", file_name="f.ulg",
            file_size=10, log_format="px4_ulog", contribute_to_dataset=True,
        )

        assert len(calls) == 1
        content, suffix, log_format, report = calls[0]
        assert content == b"fake bytes"
        assert suffix == ".ulg"
        assert log_format == "px4_ulog"

    @pytest.mark.asyncio
    async def test_opted_out_does_not_save(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            analyse_module.training_data_store, "save",
            lambda *a: calls.append(a)
        )

        await analyse_module._run_analysis_task(
            report_id="r1", content=b"fake bytes", file_name="f.ulg",
            file_size=10, log_format="px4_ulog", contribute_to_dataset=False,
        )

        assert calls == []

    @pytest.mark.asyncio
    async def test_save_failure_does_not_fail_the_job(self, monkeypatch):
        def boom(*a):
            raise RuntimeError("disk full")
        monkeypatch.setattr(analyse_module.training_data_store, "save", boom)

        # Reference the same job_store instance analyse_module actually uses
        # (module-level singletons can be swapped by other tests' fixtures).
        from api.storage import JobStatus
        job_store = analyse_module.job_store
        job_store.create("r1")

        try:
            # Must not raise.
            await analyse_module._run_analysis_task(
                report_id="r1", content=b"fake bytes", file_name="f.ulg",
                file_size=10, log_format="px4_ulog", contribute_to_dataset=True,
            )

            job = job_store.get("r1")
            assert job.status == JobStatus.COMPLETE
        finally:
            job_store._store.pop("r1", None)
