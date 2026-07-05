"""
POST /analyse — accepts a PX4 (.ulg), ArduPilot (.bin), or MAVLink telemetry
(.tlog) flight log, validates it, kicks off background analysis.
"""

import asyncio
import logging
import os
import tempfile
import uuid

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.config import get_settings
from api.storage import job_store
from flightmd_core.orchestrator import run_analysis
from flightmd_core.services.ai_enhancer import AIEnhancer
from flightmd_core.services.format_detector import (
    detect_format_from_header,
    UnsupportedFormatError,
)

logger   = logging.getLogger(__name__)
router   = APIRouter()
limiter  = Limiter(key_func=get_remote_address)
settings = get_settings()

RATE_LIMIT = f"{settings.rate_limit_per_hour}/hour"

FORMAT_SUFFIX = {
    "px4_ulog": ".ulg",
    "ardupilot_bin": ".bin",
    "mavlink_tlog": ".tlog",
}


@router.post("/analyse")
@limiter.limit(RATE_LIMIT)
async def analyse_log(
    request: Request,
    file: UploadFile = File(...),
    airframe_label: Optional[str] = Form(None),
) -> dict:
    """
    Accept a PX4 .ulg, ArduPilot .bin, or MAVLink .tlog flight log and begin
    asynchronous analysis.

    airframe_label is optional. If given, this flight is kept indefinitely
    and included in that airframe's trend history (GET /trends/{label}) —
    otherwise the report is ephemeral and expires after 1 hour, same as
    always. Nothing is retained long-term unless the uploader opts in by
    naming their airframe.

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
            detail="Invalid file. Must be a PX4 ULog (.ulg), ArduPilot (.bin), "
                   "or MAVLink telemetry (.tlog) file.",
        )

    # ── Format detection ─────────────────────────────────────────────────────
    file_name = file.filename or "flight.ulg"
    try:
        log_format = detect_format_from_header(content[:8], file_name)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Create job ───────────────────────────────────────────────────────────
    report_id = str(uuid.uuid4())
    job_store.create(report_id, airframe_label=airframe_label)

    # ── Kick off background task ─────────────────────────────────────────────
    asyncio.create_task(
        _run_analysis_task(
            report_id=report_id,
            content=content,
            file_name=file_name,
            file_size=file_size,
            log_format=log_format,
        )
    )

    logger.info(
        f"Analysis job {report_id} created for {file_name} "
        f"({log_format}, {file_size/1024:.1f}KB)"
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
    log_format: str,
) -> None:
    """
    Background task: write file to temp disk, run analysis, update job store.
    """
    tmp_path = None
    try:
        # Write to a temp file with a suffix matching the detected format —
        # the underlying parsers read binary content directly and don't
        # depend on the extension, but a matching suffix avoids surprises.
        suffix = FORMAT_SUFFIX.get(log_format, ".ulg")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        async def on_progress(progress: int, message: str):
            job_store.update_progress(report_id, progress, message)

        ai_enhancer = AIEnhancer(
            provider=settings.ai_provider,
            groq_api_key=settings.groq_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )

        report = await run_analysis(
            ulog_path=tmp_path,
            file_name=file_name,
            file_size=file_size,
            progress_callback=on_progress,
            ai_enhancer=ai_enhancer,
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
