"""
FlightMD API — FastAPI application entry point.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.config import get_settings
from api.routers import analyse, report, export, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
START_TIME = time.time()

# Rate limiter (used as dependency in routers)
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"FlightMD API v{settings.app_version} starting up")
    logger.info(f"CORS origins: {settings.cors_origins_list}")
    logger.info(f"Claude fast model: {settings.claude_fast_model}")
    logger.info(f"Claude summary model: {settings.claude_summary_model}")
    logger.info(f"Max file size: {settings.max_file_size_mb}MB")
    yield
    logger.info("FlightMD API shutting down")


app = FastAPI(
    title="FlightMD API",
    description="PX4 ULog flight log analyser — AI-powered diagnostic reports",
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

# Expose start time for uptime calculation
app.state.start_time = START_TIME
