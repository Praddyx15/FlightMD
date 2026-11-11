import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api import db, export_cache, metrics
from api.config import get_settings
from api.job_queue import get_queue, uses_redis
from api.legacy_import import LEGACY_ROOT, import_legacy
from api.routers import airframe, analyse, changes, export, health, report, trends
from api.security import trusted_networks, limiter
from api.storage import REPORT_TTL_SECONDS, job_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
access_log = logging.getLogger("flightmd.access")

settings = get_settings()

CLEANUP_INTERVAL_SECONDS = 600

# a job with no progress for this long has lost its worker
STALE_JOB_SECONDS = 3600

# multipart framing on top of the file itself
UPLOAD_OVERHEAD_BYTES = 64 * 1024


def _sweep() -> None:
    # this sweep is what makes "untagged reports expire after an hour" true
    for report_id in job_store.cleanup_expired(REPORT_TTL_SECONDS):
        export_cache.drop(report_id)
    stale = job_store.fail_stale(STALE_JOB_SECONDS)
    if stale:
        logger.warning(f"{stale} job(s) stopped making progress, marked failed")
    _remove_old_uploads(STALE_JOB_SECONDS)


def _remove_old_uploads(max_age_s: Optional[float]) -> None:
    # spool files whose job died before its own cleanup ran; None = all of them
    folder = os.path.join(db.get().data_dir, "uploads")
    if not os.path.isdir(folder):
        return
    cutoff = time.time() - max_age_s if max_age_s is not None else None
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if cutoff is None or os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except FileNotFoundError:
            pass


async def _cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_sweep)
        except Exception:
            logger.exception("cleanup sweep failed")


def _startup() -> None:
    database = db.get()
    # the engine's topic cache reads the same variable; keep it pointing at our dir
    # even when the setting only came from .env
    os.environ.setdefault("FLIGHTMD_DATA_DIR", database.data_dir)
    counts = import_legacy([LEGACY_ROOT, database.data_dir])
    if any(counts.values()):
        logger.info(f"imported legacy JSON stores: {counts}")
    if not uses_redis():
        # the in-process queue died with the old process, and its uploads with it
        job_store.interrupt_running()
        _remove_old_uploads(None)
    _sweep()


@asynccontextmanager
async def lifespan(app: FastAPI):
    trusted_networks(settings.trusted_proxies)   # a typo in TRUSTED_PROXIES should stop the boot, not 500 every request
    logger.info(f"FlightMD API v{settings.app_version} starting up")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    logger.info(f"Max file size: {settings.max_file_size_mb}MB, AI configured: {settings.ai_configured}")
    await asyncio.to_thread(_startup)
    logger.info(f"data dir: {db.get().data_dir}, queue: {'redis' if uses_redis() else 'in-process'}")
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()
    await get_queue().stop()
    logger.info("FlightMD API shutting down")


app = FastAPI(
    title="FlightMD API",
    description=(
        "Deterministic diagnostic reports for PX4 (.ulg), ArduPilot (.bin) and MAVLink (.tlog) "
        "flight logs. Reports are reachable only by their id. Airframe routes need the "
        "X-Airframe-Token handed out when the airframe is first claimed."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
metrics.instrument(app)


@app.middleware("http")
async def request_log(request: Request, call_next):
    # One JSON line per request. Route template only, never the raw path
    # (labels and ids live there), and no IPs or filenames.
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()

    if request.method == "POST" and request.url.path == "/analyse":
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > settings.max_file_size_bytes + UPLOAD_OVERHEAD_BYTES:
            response = JSONResponse(
                {"detail": f"File too large. Maximum size is {settings.max_file_size_mb}MB."},
                status_code=413,
            )
            _log_request(request, request_id, 413, start)
            response.headers["X-Request-ID"] = request_id
            return response

    try:
        response = await call_next(request)
    except Exception:
        _log_request(request, request_id, 500, start)
        raise
    _log_request(request, request_id, response.status_code, start)
    response.headers["X-Request-ID"] = request_id
    return response


def _log_request(request: Request, request_id: str, status: int, start: float) -> None:
    route = request.scope.get("route")
    access_log.info(json.dumps({
        "request_id": request_id,
        "method": request.method,
        "route": getattr(route, "path", "unmatched"),
        "status": status,
        "ms": round((time.perf_counter() - start) * 1000, 1),
    }))


# Added after the logging middleware so it wraps it, and the early 413 gets CORS headers too.
# No credentials: nothing here uses cookies, and credentials + a wildcard origin is a footgun.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-FlightMD-Schema-Version", "Content-Disposition"],
)

app.include_router(health.router)
app.include_router(analyse.router)
app.include_router(report.router)
app.include_router(export.router)
app.include_router(trends.router)
app.include_router(airframe.router)
app.include_router(changes.router)
app.include_router(metrics.router)

app.state.start_time = time.time()
