import asyncio
import logging
import os
import re
import tempfile
import uuid
import weakref
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from api import airframe_store as afs
from api.config import get_settings
from api.security import check_airframe_token, limiter, precheck_airframe_token
from api.storage import StoreFull, job_store, normalise_airframe_label
from api.training_data_store import training_data_store
from api.webhook_notifier import send_alert_webhook
from flightmd_core.orchestrator import run_analysis
from flightmd_core.services.ai_enhancer import AIEnhancer
from flightmd_core.services.format_detector import (
    detect_format_from_header,
    UnsupportedFormatError,
)

logger   = logging.getLogger(__name__)
router   = APIRouter(tags=["Analysis"])
settings = get_settings()

RATE_LIMIT = f"{settings.rate_limit_per_hour}/hour"
HEADER_BYTES = 4096   # tlog detection needs a few whole frames

FORMAT_SUFFIX = {
    "px4_ulog": ".ulg",
    "ardupilot_bin": ".bin",
    "mavlink_tlog": ".tlog",
}

BAD_FILE = "Invalid file. Must be a PX4 ULog (.ulg), ArduPilot (.bin), or MAVLink telemetry (.tlog) file."

# asyncio only keeps weak refs to tasks; without this a running analysis can be GC'd
_tasks: set[asyncio.Task] = set()
_slots = weakref.WeakKeyDictionary()   # event loop -> Semaphore

# absolute paths (two or more separators); leaves "m/s" and "1/2" alone
_PATHS = re.compile(r"(?<![\w.])(?:[A-Za-z]:)?[\\/](?:[^\s'\"\\/:]+[\\/])+[^\s'\"\\/:]*")


class UploadTooLarge(Exception):
    pass


def _analysis_slots() -> asyncio.Semaphore:
    # one per event loop: a semaphore is bound to the loop it first waits on
    # (only matters in tests, where every test gets a fresh loop)
    loop = asyncio.get_running_loop()
    sem = _slots.get(loop)
    if sem is None:
        sem = _slots[loop] = asyncio.Semaphore(max(1, settings.max_concurrent_analyses))
    return sem


def public_error(e: Exception) -> str:
    """What a client may see about a failed analysis.

    The parsers raise ValueError with a usable message for bad input; anything
    else is our bug, and its text (with temp paths in it) stays in the log.
    """
    if isinstance(e, (ValueError, UnsupportedFormatError)):
        msg = _PATHS.sub("<file>", str(e)).strip()
        return msg[:300] or "The log could not be analysed."
    return "Analysis failed because of an internal error."


def _save_upload(src, suffix: str, limit: int) -> tuple[str, int]:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="flightmd-")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := src.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge()
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return path, size


def _remove(path: Optional[str]) -> None:
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@router.post(
    "/analyse",
    summary="Upload a flight log",
    responses={
        400: {"description": "Not a supported log, or a bad airframe label"},
        401: {"description": "Airframe is claimed and X-Airframe-Token is missing"},
        403: {"description": "Wrong X-Airframe-Token"},
        413: {"description": "File too large"},
        429: {"description": "Rate limited"},
        503: {"description": "Too many analyses running"},
    },
)
@limiter.limit(RATE_LIMIT)
async def analyse_log(
    request: Request,
    file: UploadFile = File(...),
    airframe_label: Optional[str] = Form(None),
    contribute_to_dataset: bool = Form(False),
    x_airframe_token: Optional[str] = Header(None),
) -> dict:
    """Start analysing a PX4 .ulg, ArduPilot .bin or MAVLink .tlog. Poll /status/{report_id}.

    Untagged reports expire after an hour. `airframe_label` keeps the report in
    that airframe's trend history: a new label is claimed by this upload and the
    response carries `airframe_token` once; an already claimed one needs the
    X-Airframe-Token header. `contribute_to_dataset` keeps the raw log and a
    stripped copy of the report (no filename, place name or GPS track).
    """
    head = await file.read(HEADER_BYTES)
    if len(head) < 8:
        raise HTTPException(status_code=400, detail=BAD_FILE)

    file_name = file.filename or "flight.ulg"
    try:
        log_format = detect_format_from_header(head, file_name, complete=len(head) < HEADER_BYTES)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    label = normalise_airframe_label(airframe_label)
    if airframe_label and airframe_label.strip() and label is None:
        raise HTTPException(status_code=400, detail="Invalid airframe label (no slashes or control characters).")

    needs_claim = False
    if label:
        needs_claim = await run_in_threadpool(precheck_airframe_token, label, x_airframe_token)

    await file.seek(0)
    suffix = FORMAT_SUFFIX.get(log_format, ".ulg")
    try:
        tmp_path, file_size = await run_in_threadpool(
            _save_upload, file.file, suffix, settings.max_file_size_bytes
        )
    except UploadTooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_file_size_mb}MB.",
        )

    report_id = str(uuid.uuid4())
    try:
        job_store.create(report_id, airframe_label=label)
    except StoreFull:
        _remove(tmp_path)
        raise HTTPException(status_code=503, detail="Too many analyses in progress. Try again in a minute.")

    # claim only now, so a 413 or 503 above can't burn the one-time token
    new_token = None
    if needs_claim:
        try:
            new_token = await run_in_threadpool(check_airframe_token, label, x_airframe_token, True)
        except HTTPException:
            # someone else claimed it in between
            job_store.discard(report_id)
            _remove(tmp_path)
            raise

    task = asyncio.create_task(
        _run_analysis_task(
            report_id=report_id,
            log_path=tmp_path,
            file_name=file_name,
            file_size=file_size,
            log_format=log_format,
            airframe_label=label,
            contribute_to_dataset=contribute_to_dataset,
        )
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    logger.info(f"job {report_id} created ({log_format}, {file_size / 1024:.1f}KB)")

    out = {
        "report_id":        report_id,
        "status":           "processing",
        "estimated_seconds": 20,
    }
    if new_token:
        out["airframe_token"] = new_token
    return out


@router.get("/dataset/stats", tags=["Dataset"], summary="How many logs have been contributed")
def dataset_stats() -> dict:
    stats = training_data_store.stats()
    return {"contributed_logs": stats.count, "total_bytes": stats.total_bytes}


async def _run_analysis_task(
    report_id: str,
    log_path: str,
    file_name: str,
    file_size: int,
    log_format: str,
    airframe_label: Optional[str] = None,
    contribute_to_dataset: bool = False,
) -> None:
    """Runs one analysis and always removes log_path afterwards."""
    try:
        job_store.update_progress(report_id, 0, "Queued…")
        async with _analysis_slots():
            async def on_progress(progress: int, message: str):
                job_store.update_progress(report_id, progress, message)

            ai_enhancer = AIEnhancer(
                provider=settings.ai_provider,
                groq_api_key=settings.groq_api_key,
                anthropic_api_key=settings.anthropic_api_key,
            )
            report = await run_analysis(
                ulog_path=log_path,
                file_name=file_name,
                file_size=file_size,
                progress_callback=on_progress,
                ai_enhancer=ai_enhancer,
            )

        # the orchestrator makes up its own id
        report.report_id = report_id
        await run_in_threadpool(job_store.complete, report_id, report)
        logger.info(f"job {report_id} complete: {report.overall_score}/100")

        if airframe_label:
            await _check_alert_rules(airframe_label, report_id, report)

        if contribute_to_dataset:
            suffix = FORMAT_SUFFIX.get(log_format, ".ulg")
            try:
                await run_in_threadpool(training_data_store.save, log_path, suffix, log_format, report)
            except Exception as e:
                # the uploader's report is already done; a dataset hiccup mustn't touch it
                logger.error(f"dataset contribution for {report_id} not saved: {e}")

    except Exception as e:
        if isinstance(e, (ValueError, UnsupportedFormatError)):
            logger.info(f"job {report_id} rejected: {e}")
        else:
            logger.error(f"job {report_id} failed", exc_info=True)
        job_store.fail(report_id, public_error(e))
    finally:
        _remove(log_path)


async def _check_alert_rules(airframe_label: str, report_id: str, report) -> None:
    """Fire the airframe's webhook for any breached rule. Never raises."""
    try:
        config = await run_in_threadpool(afs.airframe_store.get, airframe_label)
        if not config.alert_rules or not config.webhook_url:
            return
        triggered = afs.evaluate_alert_rules(report, config.alert_rules)
        if not triggered:
            return
        sent = await run_in_threadpool(
            send_alert_webhook, config.webhook_url, airframe_label, report_id, triggered
        )
        logger.info(f"alert webhook for {report_id} ({len(triggered)} rule(s)): {'sent' if sent else 'failed'}")
    except Exception as e:
        logger.error(f"alert rule check failed for {report_id}: {e}")
