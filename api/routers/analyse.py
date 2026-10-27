import hashlib
import logging
import os
import re
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from api import db, metrics
from api.analysis import AnalysisJob, remove_file
from api.config import get_settings
from api.job_queue import get_queue
from api.security import check_airframe_token, limiter, precheck_airframe_token
from api.storage import REPORT_TTL_SECONDS, StoreFull, job_store, normalise_airframe_label
from api.training_data_store import CONTRIBUTION_ID_RE, contribution_id_for, training_data_store
from flightmd_core.services.format_detector import (
    detect_format_from_header,
    UnsupportedFormatError,
)

logger   = logging.getLogger(__name__)
router   = APIRouter(tags=["Analysis"])
settings = get_settings()

RATE_LIMIT = f"{settings.rate_limit_per_hour}/hour"
HEADER_BYTES = 4096   # tlog detection needs a few whole frames
ESTIMATED_SECONDS = 20

FORMAT_SUFFIX = {
    "px4_ulog": ".ulg",
    "ardupilot_bin": ".bin",
    "ardupilot_log": ".log",
    "mavlink_tlog": ".tlog",
    "betaflight_bbl": ".bbl",
    "dji_txt": ".txt",
    "dji_dat": ".dat",
}

# The engine unpacks these itself (and enforces the unpacked size); here
# they only need the right suffix and the compressed-size cap.
COMPRESSED_MAGIC = {b"\x1f\x8b": ".gz", b"PK\x03\x04": ".zip"}

BAD_FILE = "Invalid file. Must be a PX4 ULog (.ulg), ArduPilot (.bin), or MAVLink telemetry (.tlog) file."

BRIEF_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class UploadTooLarge(Exception):
    pass


def _uploads_dir() -> str:
    # inside the data dir, not /tmp: with the Redis queue another process reads it
    path = os.path.join(db.get().data_dir, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


def _save_upload(src, suffix: str, limit: int) -> tuple[str, int, str]:
    """Stream the upload to disk. Returns (path, size, sha256 of the bytes)."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="flightmd-", dir=_uploads_dir())
    size = 0
    h = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := src.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise UploadTooLarge()
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return path, size, h.hexdigest()


def _detect(head: bytes, file_name: str) -> tuple[str, str]:
    """(format id, file suffix) for an upload's first bytes. Raises HTTPException(400)."""
    for magic, suffix in COMPRESSED_MAGIC.items():
        if head.startswith(magic):
            return "compressed", suffix
    try:
        log_format = detect_format_from_header(head, file_name, complete=len(head) < HEADER_BYTES)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return log_format, FORMAT_SUFFIX.get(log_format, ".ulg")


@router.post(
    "/analyse",
    summary="Upload a flight log",
    responses={
        400: {"description": "Not a supported log, a bad airframe label or a bad brief hash"},
        401: {"description": "Airframe is claimed and X-Airframe-Token is missing"},
        403: {"description": "Wrong X-Airframe-Token"},
        413: {"description": "File too large"},
        429: {"description": "Rate limited"},
        503: {"description": "Too many analyses queued"},
    },
)
@limiter.limit(RATE_LIMIT)
async def analyse_log(
    request: Request,
    file: UploadFile = File(...),
    airframe_label: Optional[str] = Form(None),
    contribute_to_dataset: bool = Form(False),
    planning_brief_sha256: Optional[str] = Form(None),
    x_airframe_token: Optional[str] = Header(None),
) -> dict:
    """Start analysing a flight log. Poll /status/{report_id}.

    Untagged reports expire after an hour. `airframe_label` keeps the report in
    that airframe's trend history: a new label is claimed by this upload and the
    response carries `airframe_token` once; an already claimed one needs the
    X-Airframe-Token header. `contribute_to_dataset` keeps the raw log and a
    stripped copy of the report (no filename, place name or GPS track); the
    response then carries `contribution_id`, which DELETE /dataset/{id} takes.
    `planning_brief_sha256` is AeroAtlas's brief hash, copied into the report.

    The same bytes uploaded again within the hour (same airframe tag and brief
    hash) get the existing report back with `deduplicated: true`.
    """
    head = await file.read(HEADER_BYTES)
    if len(head) < 8:
        raise HTTPException(status_code=400, detail=BAD_FILE)

    file_name = file.filename or "flight.ulg"
    log_format, suffix = _detect(head, file_name)

    label = normalise_airframe_label(airframe_label)
    if airframe_label and airframe_label.strip() and label is None:
        raise HTTPException(status_code=400, detail="Invalid airframe label (no slashes or control characters).")

    brief = None
    if planning_brief_sha256 and planning_brief_sha256.strip():
        brief = planning_brief_sha256.strip()
        if not BRIEF_HASH_RE.match(brief):
            raise HTTPException(status_code=400, detail="planning_brief_sha256 must be 64 hex characters.")
        brief = brief.lower()

    needs_claim = False
    if label:
        needs_claim = await run_in_threadpool(precheck_airframe_token, label, x_airframe_token)

    await file.seek(0)
    try:
        tmp_path, file_size, sha = await run_in_threadpool(
            _save_upload, file.file, suffix, settings.max_file_size_bytes
        )
    except UploadTooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.max_file_size_mb}MB.",
        )

    # A contributing upload always runs: the earlier one may not have contributed.
    # A claiming one can't match anything, its label has no reports yet.
    if not contribute_to_dataset and not needs_claim:
        dup = await run_in_threadpool(job_store.find_recent_duplicate, sha, label, brief, REPORT_TTL_SECONDS)
        if dup:
            remove_file(tmp_path)
            metrics.count_analysis(log_format, "deduplicated")
            report_id, status = dup
            logger.info(f"upload matches job {report_id}, not analysed again")
            return {
                "report_id": report_id,
                "status": status,
                "estimated_seconds": 0 if status == "complete" else ESTIMATED_SECONDS,
                "deduplicated": True,
            }

    report_id = str(uuid.uuid4())
    try:
        await run_in_threadpool(job_store.create, report_id, label, sha, brief, log_format)
    except StoreFull:
        remove_file(tmp_path)
        raise HTTPException(status_code=503, detail="Too many analyses in progress. Try again in a minute.")

    # claim only now, so a 413 or 503 above can't burn the one-time token
    new_token = None
    if needs_claim:
        try:
            new_token = await run_in_threadpool(check_airframe_token, label, x_airframe_token, True)
        except HTTPException:
            # someone else claimed it in between
            await run_in_threadpool(job_store.discard, report_id)
            remove_file(tmp_path)
            raise

    job = AnalysisJob(
        report_id=report_id,
        log_path=tmp_path,
        file_name=file_name,
        file_size=file_size,
        log_format=log_format,
        airframe_label=label,
        contribute_to_dataset=contribute_to_dataset,
        log_sha256=sha,
        planning_brief_sha256=brief,
    )
    try:
        await get_queue().submit(job)
    except Exception:
        logger.exception(f"could not queue job {report_id}")
        await run_in_threadpool(job_store.fail, report_id, "could not be queued")
        remove_file(tmp_path)
        raise HTTPException(status_code=503, detail="The analysis queue is unavailable. Try again in a minute.")

    logger.info(f"job {report_id} queued ({log_format}, {file_size / 1024:.1f}KB)")

    out = {
        "report_id":         report_id,
        "status":            "processing",
        "estimated_seconds": ESTIMATED_SECONDS,
        "deduplicated":      False,
    }
    if new_token:
        out["airframe_token"] = new_token
    if contribute_to_dataset:
        out["contribution_id"] = contribution_id_for(sha)
    return out


@router.get("/dataset/stats", tags=["Dataset"], summary="How many logs have been contributed")
def dataset_stats() -> dict:
    stats = training_data_store.stats()
    return {"contributed_logs": stats.count, "total_bytes": stats.total_bytes}


@router.delete(
    "/dataset/{contribution_id}",
    tags=["Dataset"],
    status_code=204,
    summary="Withdraw a contributed log",
    responses={404: {"description": "No contribution with that id"}},
)
def withdraw_contribution(contribution_id: str) -> None:
    """Deletes the raw log and its stripped report. The id is the `contribution_id`
    returned by the upload; it is derived from the log's bytes, so whoever has the
    log or the id can withdraw it."""
    # todo: a withdraw that arrives while the analysis is still running 404s, and the
    # job then saves the contribution anyway; needs a tombstone row
    if not CONTRIBUTION_ID_RE.match(contribution_id) or not training_data_store.delete(contribution_id):
        raise HTTPException(status_code=404, detail="No contribution with that id.")
