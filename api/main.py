import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.config import get_settings
from api.routers import airframe, analyse, export, health, report, trends
from api.security import trusted_networks, limiter
from api.storage import job_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
access_log = logging.getLogger("flightmd.access")

settings = get_settings()

CLEANUP_INTERVAL_SECONDS = 600
REPORT_TTL_SECONDS = 3600

# multipart framing on top of the file itself
UPLOAD_OVERHEAD_BYTES = 64 * 1024


async def _cleanup_loop():
    # this sweep is what makes "untagged reports expire after an hour" true
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(job_store.cleanup_expired_disk_reports, REPORT_TTL_SECONDS)
        except Exception:
            logger.exception("report cleanup sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    trusted_networks(settings.trusted_proxies)   # a typo in TRUSTED_PROXIES should stop the boot, not 500 every request
    logger.info(f"FlightMD API v{settings.app_version} starting up")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    logger.info(f"Max file size: {settings.max_file_size_mb}MB, AI configured: {settings.ai_configured}")
    await asyncio.to_thread(job_store.cleanup_expired_disk_reports, REPORT_TTL_SECONDS)
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()
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

app.state.start_time = time.time()
