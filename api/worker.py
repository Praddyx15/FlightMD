"""
arq worker for the opt-in Redis queue:

    FLIGHTMD_REDIS_URL=redis://localhost:6379 arq api.worker.WorkerSettings

Needs the `queue` extra and the same FLIGHTMD_DATA_DIR as the API (the
uploads and the database are shared through it).
"""

from arq.connections import RedisSettings

from api.analysis import AnalysisJob, run_job
from api.config import get_settings

settings = get_settings()

# a bit over the engine's own parse timeout (FLIGHTMD_PARSE_TIMEOUT_S, 600 by default)
JOB_TIMEOUT_S = 900


async def analyse(ctx, payload: dict) -> None:
    await run_job(AnalysisJob(**payload))


class WorkerSettings:
    functions = [analyse]
    redis_settings = RedisSettings.from_dsn(settings.flightmd_redis_url or "redis://localhost:6379")
    max_jobs = max(1, settings.max_concurrent_analyses)
    job_timeout = JOB_TIMEOUT_S
    # a retry would find the upload already deleted by run_job
    max_tries = 1
