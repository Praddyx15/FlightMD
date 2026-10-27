"""
The analysis queue: N in-process workers, never more analyses at once than
that, Redis only when configured, and startup turning jobs that were running
into "interrupted" failures.
"""

import asyncio
import sys

import pytest

import api.job_queue as job_queue
from api import db
from api.analysis import AnalysisJob
from api.storage import JobStatus, job_store


def job(report_id):
    return AnalysisJob(report_id=report_id, log_path="/nonexistent", file_name="f.ulg",
                       file_size=1, log_format="px4_ulog")


@pytest.fixture
def database(tmp_path, monkeypatch):
    d = db.Database(str(tmp_path / "data"))
    monkeypatch.setattr(db, "_db", d)
    yield d
    d.close()


class TestLocalQueue:
    @pytest.mark.asyncio
    async def test_runs_every_job_with_at_most_n_at_once(self, monkeypatch):
        running = 0
        peak = 0
        done = []

        async def fake_run_job(j):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            done.append(j.report_id)
        monkeypatch.setattr(job_queue, "run_job", fake_run_job)

        q = job_queue.LocalQueue(workers=2)
        for i in range(6):
            await q.submit(job(f"r{i}"))
        await asyncio.wait_for(q._queue.join(), timeout=5)
        await q.stop()

        assert sorted(done) == [f"r{i}" for i in range(6)]
        assert peak == 2

    @pytest.mark.asyncio
    async def test_a_crashing_job_does_not_kill_the_worker(self, monkeypatch):
        done = []

        async def flaky(j):
            if j.report_id == "bad":
                raise RuntimeError("bug")
            done.append(j.report_id)
        monkeypatch.setattr(job_queue, "run_job", flaky)

        q = job_queue.LocalQueue(workers=1)
        await q.submit(job("bad"))
        await q.submit(job("good"))
        await asyncio.wait_for(q._queue.join(), timeout=5)
        await q.stop()
        assert done == ["good"]

    @pytest.mark.asyncio
    async def test_zero_workers_still_means_one(self):
        assert job_queue.LocalQueue(workers=0).workers == 1

    @pytest.mark.asyncio
    async def test_depth(self, monkeypatch):
        gate = asyncio.Event()

        async def blocked(j):
            await gate.wait()
        monkeypatch.setattr(job_queue, "run_job", blocked)

        q = job_queue.LocalQueue(workers=1)
        for i in range(3):
            await q.submit(job(f"r{i}"))
        await asyncio.sleep(0)
        assert q.depth == 2
        gate.set()
        await asyncio.wait_for(q._queue.join(), timeout=5)
        await q.stop()


class TestQueueChoice:
    def test_in_process_by_default(self, monkeypatch):
        from api.config import get_settings
        monkeypatch.setattr(get_settings(), "flightmd_redis_url", "")
        monkeypatch.setattr(job_queue, "_queue", None)
        assert isinstance(job_queue.get_queue(), job_queue.LocalQueue)
        assert job_queue.uses_redis() is False

    def test_redis_when_configured(self, monkeypatch):
        from api.config import get_settings
        monkeypatch.setattr(get_settings(), "flightmd_redis_url", "redis://localhost:6379")
        monkeypatch.setattr(job_queue, "_queue", None)
        assert isinstance(job_queue.get_queue(), job_queue.RedisQueue)
        assert job_queue.uses_redis() is True

    @pytest.mark.asyncio
    async def test_redis_without_arq_says_what_to_install(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "arq", None)
        with pytest.raises(RuntimeError, match=r"flightmd-core\[queue\]"):
            await job_queue.RedisQueue("redis://localhost:6379").submit(job("r1"))


class TestStartup:
    def test_running_jobs_fail_as_interrupted_and_finished_ones_stay(self, database, monkeypatch):
        import api.main as main
        from api.config import get_settings
        from flightmd_core.models.findings import FlightMDReport
        from flightmd_core.models.metadata import FlightMetadata

        monkeypatch.setattr(get_settings(), "flightmd_redis_url", "")
        monkeypatch.setattr(main, "LEGACY_ROOT", database.data_dir)
        monkeypatch.setenv("FLIGHTMD_DATA_DIR", database.data_dir)
        job_store.create("was-running")
        job_store.create("was-done")
        job_store.complete("was-done", FlightMDReport(
            report_id="was-done", overall_score=85.0, score_label="Good", letter_grade="B",
            executive_summary="s", metadata=FlightMetadata(duration_seconds=60.0),
            findings=[], param_change_sheet=[], analyser_results=[],
            processing_time_ms=10, file_name="f.ulg", file_size_bytes=100,
        ))

        main._startup()

        status = job_store.status_summary("was-running")
        assert status["status"] == "failed"
        assert status["error"].startswith("interrupted")
        assert job_store.get("was-done").status == JobStatus.COMPLETE

    def test_with_redis_the_workers_keep_their_jobs(self, database, monkeypatch):
        import api.main as main
        from api.config import get_settings

        monkeypatch.setattr(get_settings(), "flightmd_redis_url", "redis://localhost:6379")
        monkeypatch.setattr(main, "LEGACY_ROOT", database.data_dir)
        monkeypatch.setenv("FLIGHTMD_DATA_DIR", database.data_dir)
        job_store.create("in-a-worker")

        main._startup()

        assert job_store.get("in-a-worker").status == JobStatus.PROCESSING

    def test_orphaned_uploads_are_removed(self, database, monkeypatch):
        import os
        import api.main as main
        from api.config import get_settings

        monkeypatch.setattr(get_settings(), "flightmd_redis_url", "")
        monkeypatch.setattr(main, "LEGACY_ROOT", database.data_dir)
        monkeypatch.setenv("FLIGHTMD_DATA_DIR", database.data_dir)
        uploads = os.path.join(database.data_dir, "uploads")
        os.makedirs(uploads)
        with open(os.path.join(uploads, "flightmd-x.ulg"), "wb") as f:
            f.write(b"x")

        main._startup()

        assert os.listdir(uploads) == []
