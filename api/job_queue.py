"""
Analysis queue.

Default: an asyncio.Queue drained by MAX_CONCURRENT_ANALYSES worker tasks in
the API process, which caps memory on a 512 MB box. This assumes one API
process; with several, set FLIGHTMD_REDIS_URL so arq workers (api/worker.py)
take the jobs instead. Either way the job state is in the database, so the
queue itself holds nothing that /status needs.
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Optional

from api.analysis import AnalysisJob, run_job
from api.config import get_settings

logger = logging.getLogger(__name__)


class LocalQueue:
    def __init__(self, workers: int):
        self.workers = max(1, workers)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        # strong refs: asyncio only keeps weak ones, an unreferenced worker can be GC'd
        self._tasks: set[asyncio.Task] = set()

    def _ensure_started(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        # first use, or a new event loop (every test gets one); the old loop's
        # queue and tasks went wiht it
        self._loop = loop
        self._queue = asyncio.Queue()
        self._tasks = {loop.create_task(self._worker(i)) for i in range(self.workers)}

    async def submit(self, job: AnalysisJob) -> None:
        self._ensure_started()
        self._queue.put_nowait(job)

    async def _worker(self, n: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                await run_job(job)
            except Exception:
                # run_job already catches everything; this keeps the worker alive regardless
                logger.exception(f"queue worker {n} hit an error")
            finally:
                self._queue.task_done()

    @property
    def depth(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = set()
        self._loop = None


class RedisQueue:
    def __init__(self, url: str):
        self.url = url
        self._pool = None

    async def submit(self, job: AnalysisJob) -> None:
        if self._pool is None:
            try:
                from arq import create_pool
                from arq.connections import RedisSettings
            except ImportError as e:
                raise RuntimeError(
                    "FLIGHTMD_REDIS_URL is set but arq isn't installed: pip install 'flightmd-core[queue]'"
                ) from e
            self._pool = await create_pool(RedisSettings.from_dsn(self.url))
        # report id as the arq job id, so a retried enqueue can't run twice
        await self._pool.enqueue_job("analyse", asdict(job), _job_id=job.report_id)

    @property
    def depth(self) -> int:
        return 0   # lives in Redis; arq has its own tooling for that

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


_queue = None


def get_queue():
    global _queue
    if _queue is None:
        s = get_settings()
        _queue = RedisQueue(s.flightmd_redis_url) if s.flightmd_redis_url else LocalQueue(s.max_concurrent_analyses)
    return _queue


def uses_redis() -> bool:
    return bool(get_settings().flightmd_redis_url)
