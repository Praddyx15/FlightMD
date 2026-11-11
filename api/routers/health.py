import time

from fastapi import APIRouter, Request

from api.config import get_settings
from api.storage import job_store
from flightmd_core.models.findings import FlightMDReport

router = APIRouter(tags=["Health"])

SCHEMA_VERSION = FlightMDReport.model_fields["schema_version"].default


@router.get("/health", summary="Liveness, versions, and whether AI is set up")
async def health_check(request: Request):
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "schema_version": SCHEMA_VERSION,
        "ai_configured": settings.ai_configured,
        "uptime_seconds": int(time.time() - request.app.state.start_time),
        "active_jobs": job_store.job_count,
    }
