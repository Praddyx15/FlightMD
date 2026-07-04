"""
POST /analyse — accepts a .ulg file, validates it, kicks off background analysis.
"""

import asyncio
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.config import get_settings
from api.storage import job_store
from flightmd_core.orchestrator import run_analysis

logger   = logging.getLogger(__name__)
router   = APIRouter()
limiter  = Limiter(key_func=get_remote_address)
settings = get_settings()

# PX4 ULog magic bytes: "ULog" = 0x55 0x4C 0x6F 0x67
ULOG_MAGIC = b"\x55\x4C\x6F\x67"

RATE_LIMIT = f"{settings.rate_limit_per_hour}/hour"


@router.post("/analyse")
@limiter.limit(RATE_LIMIT)
async def analyse_log(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """
    Accept a PX4 .ulg file and begin asynchronous analysis.

    Returns immediately with a report_id and estimated processing time.
    Poll GET /status/{report_id} for progress.
    """
    # ── File size check ──────────────────────────────────────────────────────
    content = await file.read()
    file_size = len(content)

    if file_size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_file_size_mb}MB.",
        )

    if file_size < 8:
        raise HTTPException(
            status_code=400,
            detail="Invalid file. Must be a PX4 ULog (.ulg) file.",
        )

    # ── ULog magic bytes check ───────────────────────────────────────────────
    if content[:4] != ULOG_MAGIC:
        raise HTTPException(
            status_code=400,
            detail="Invalid file. Must be a PX4 ULog (.ulg) file.",
        )

    # ── Create job ───────────────────────────────────────────────────────────
    report_id = str(uuid.uuid4())
    job = job_store.create(report_id)
    file_name = file.filename or "flight.ulg"

    # ── Kick off background task ─────────────────────────────────────────────
    asyncio.create_task(
        _run_analysis_task(
            report_id=report_id,
            content=content,
            file_name=file_name,
            file_size=file_size,
        )
    )

    logger.info(
        f"Analysis job {report_id} created for {file_name} "
        f"({file_size/1024:.1f}KB)"
    )

    return {
        "report_id":        report_id,
        "status":           "processing",
        "estimated_seconds": 20,
    }


async def _run_analysis_task(
    report_id: str,
    content: bytes,
    file_name: str,
    file_size: int,
) -> None:
    """
    Background task: write file to temp disk, run analysis, update job store.
    """
    tmp_path = None
    try:
        # Write to a temp file (pyulog needs a real file path)
        with tempfile.NamedTemporaryFile(suffix=".ulg", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        async def on_progress(progress: int, message: str):
            job_store.update_progress(report_id, progress, message)

        report = await run_analysis(
            ulog_path=tmp_path,
            file_name=file_name,
            file_size=file_size,
            anthropic_api_key=get_settings().anthropic_api_key,
            use_claude=bool(get_settings().anthropic_api_key),
            progress_callback=on_progress,
        )

        # Override the report_id with our assigned one (orchestrator generates its own)
        report.report_id = report_id
        job_store.complete(report_id, report)
        logger.info(f"Job {report_id} complete: {report.overall_score}/100")

    except Exception as e:
        logger.error(f"Job {report_id} failed: {e}", exc_info=True)
        job_store.fail(report_id, str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
