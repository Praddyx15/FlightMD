"""
FlightMD API — FastAPI application entry point.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.config import get_settings
from api.routers import analyse, report, export, health, trends
from api.storage import job_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
START_TIME = time.time()

# Rate limiter (used as dependency in routers)
limiter = Limiter(key_func=get_remote_address)

CLEANUP_INTERVAL_SECONDS = 600  # 10 minutes


async def _cleanup_loop():
    """Periodically deletes expired *untagged* reports from disk — this is
    what actually enforces the "reports expire after 1 hour" claim. Reports
    tagged with an airframe_label are never touched here; that's the
    opt-in trend-history retention."""
    while True:
        try:
            job_store.cleanup_expired_disk_reports(ttl_seconds=3600)
        except Exception as e:
            logger.error(f"Report cleanup sweep failed: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"FlightMD API v{settings.app_version} starting up")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    logger.info(f"Max file size: {settings.max_file_size_mb}MB")
    job_store.cleanup_expired_disk_reports(ttl_seconds=3600)
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()
    logger.info("FlightMD API shutting down")


app = FastAPI(
    title="FlightMD API",
    description="PX4 ULog flight log analyser — deterministic diagnostic reports",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(analyse.router, tags=["Analysis"])
app.include_router(report.router, tags=["Reports"])
app.include_router(export.router, tags=["Export"])
app.include_router(trends.router, tags=["Trends"])

# Expose start time for uptime calculation
app.state.start_time = START_TIME
