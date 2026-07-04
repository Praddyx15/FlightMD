import time
from fastapi import APIRouter, Request
from api.storage import job_store

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    uptime = int(time.time() - request.app.state.start_time)
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": uptime,
        "active_jobs": job_store.job_count,
    }
