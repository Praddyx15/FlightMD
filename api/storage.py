"""
In-memory job store (Phase 1).

Phase 3: swap this module for a Redis/Supabase-backed implementation.
The interface (get_job, set_job, update_progress, etc.) stays the same.

Retention model:
  - Untagged reports (no airframe_label given at upload) are ephemeral —
    the 1-hour TTL advertised to users is enforced for real via
    cleanup_expired_disk_reports(), called periodically from the API
    lifespan and swept once on startup.
  - Reports tagged with an airframe_label are kept indefinitely so
    cross-flight trend analysis has history to work with. This is opt-in:
    nothing is retained past 1 hour unless the uploader explicitly asks
    for it by naming their airframe.

Limits:
  - Max 100 concurrent in-memory jobs (free tier constraint)
  - LRU eviction of in-memory (non-persisted) state when at capacity
"""

import os
import json
import time
import logging
import threading
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETE   = "complete"
    FAILED     = "failed"


@dataclass
class Job:
    report_id: str
    status: JobStatus = JobStatus.PROCESSING
    progress: int = 0
    message: str = ""
    report: Optional[FlightMDReport] = None
    error: Optional[str] = None
    airframe_label: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 3600   # 1 hour — only enforced for untagged reports

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


MAX_AIRFRAME_LABEL_LEN = 40


def normalise_airframe_label(label: Optional[str]) -> Optional[str]:
    """Trim, cap length, and collapse an empty/whitespace-only label to
    None so 'no label given' and 'gave an empty string' behave identically."""
    if label is None:
        return None
    label = label.strip()[:MAX_AIRFRAME_LABEL_LEN]
    return label or None


class JobStore:
    """
    Thread-safe in-memory job store with disk-backed persistence for
    completed reports.
    """
    MAX_JOBS = 100
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "reports"))

    def __init__(self):
        self._store: dict[str, Job] = {}
        self._lock  = threading.Lock()
        os.makedirs(self.DATA_DIR, exist_ok=True)

    def create(self, report_id: str, airframe_label: Optional[str] = None) -> Job:
        """Create a new job and store it. Evict oldest if at capacity."""
        with self._lock:
            self._evict_expired()
            if len(self._store) >= self.MAX_JOBS:
                self._evict_oldest()
            job = Job(report_id=report_id, airframe_label=normalise_airframe_label(airframe_label))
            self._store[report_id] = job
            return job

    def get(self, report_id: str) -> Optional[Job]:
        """Retrieve a job by ID. Checks memory first, then loads from disk if missing."""
        with self._lock:
            job = self._store.get(report_id)
            if job is None:
                loaded = self._load_from_disk(report_id)
                if loaded is not None:
                    self._store[report_id] = loaded
                return loaded

            if job.is_expired:
                # Don't delete from memory if complete, but evict other states if expired
                if job.status != JobStatus.COMPLETE:
                    del self._store[report_id]
                    return None
            return job

    def update_progress(self, report_id: str, progress: int, message: str = "") -> None:
        """Update job progress (0–100) and optional status message."""
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.progress = min(100, max(0, progress))
                job.message  = message

    def complete(self, report_id: str, report: FlightMDReport) -> None:
        """Mark job as complete, attach the finished report, and persist to disk."""
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.status   = JobStatus.COMPLETE
                job.progress = 100
                job.report   = report
                job.message  = "Analysis complete."

            airframe_label = job.airframe_label if job else None
            created_at     = job.created_at if job else time.time()

            try:
                path = os.path.join(self.DATA_DIR, f"{report_id}.json")
                wrapper = {
                    "airframe_label": airframe_label,
                    "created_at": created_at,
                    "report": report.model_dump(mode="json"),
                }
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(wrapper, f)
            except Exception as e:
                logger.error(f"Failed to save report {report_id} to disk: {e}")

    def fail(self, report_id: str, error: str) -> None:
        """Mark job as failed with an error message."""
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.status = JobStatus.FAILED
                job.error  = error
                job.message = f"Analysis failed: {error}"

    def status_summary(self, report_id: str) -> dict:
        """Return a minimal status dict for the /status endpoint."""
        job = self.get(report_id)
        if job is None:
            return {"status": "not_found"}
        result = {
            "status":   job.status.value,
            "progress": job.progress,
            "message":  job.message,
        }
        if job.error:
            result["error"] = job.error
        return result

    def get_all_reports(self) -> list[dict]:
        """Read and return summaries of all completed reports stored on disk."""
        summaries = []
        if not os.path.exists(self.DATA_DIR):
            return []

        with self._lock:
            for filename in os.listdir(self.DATA_DIR):
                if not filename.endswith(".json"):
                    continue
                report_id = filename[:-5]
                path = os.path.join(self.DATA_DIR, filename)
                try:
                    wrapper = self._read_wrapper(path)
                except Exception as e:
                    logger.error(f"Failed to read report {filename} for summary: {e}")
                    continue
                if wrapper is None:
                    continue

                data = wrapper["report"]
                meta = data.get("metadata") or {}
                weather = meta.get("weather") or {}
                summaries.append({
                    "report_id": report_id,
                    "file_name": data.get("file_name", "Unknown"),
                    "file_size_bytes": data.get("file_size_bytes", 0),
                    "overall_score": data.get("overall_score", 0.0),
                    "score_label": data.get("score_label", "Unknown"),
                    "letter_grade": data.get("letter_grade", "F"),
                    "duration_seconds": meta.get("duration_seconds", 0.0),
                    "firmware_version": meta.get("firmware_version", ""),
                    "vehicle_type": meta.get("vehicle_type", ""),
                    "weather_desc": weather.get("description", "N/A"),
                    "airframe_label": wrapper["airframe_label"],
                    "created_at": wrapper["created_at"],
                })

        summaries.sort(key=lambda x: x["created_at"], reverse=True)
        return summaries

    def list_by_airframe_with_created_at(self, airframe_label: str) -> list[tuple[float, FlightMDReport]]:
        """Return (created_at, report) pairs for every completed report
        tagged with this airframe label, oldest first, for trend analysis."""
        airframe_label = normalise_airframe_label(airframe_label)
        if not airframe_label:
            return []

        reports: list[tuple[float, FlightMDReport]] = []
        if not os.path.exists(self.DATA_DIR):
            return []

        with self._lock:
            for filename in os.listdir(self.DATA_DIR):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(self.DATA_DIR, filename)
                try:
                    wrapper = self._read_wrapper(path)
                except Exception as e:
                    logger.error(f"Failed to read report {filename} for trend listing: {e}")
                    continue
                if wrapper is None or wrapper["airframe_label"] != airframe_label:
                    continue
                reports.append((wrapper["created_at"], FlightMDReport.model_validate(wrapper["report"])))

        reports.sort(key=lambda pair: pair[0])
        return reports

    def list_by_airframe(self, airframe_label: str) -> list[FlightMDReport]:
        """Return every completed report tagged with this airframe label,
        oldest first, for trend analysis."""
        return [r for _, r in self.list_by_airframe_with_created_at(airframe_label)]

    def cleanup_expired_disk_reports(self, ttl_seconds: int = 3600) -> int:
        """
        Delete untagged report files older than ttl_seconds. Tagged
        (airframe_label set) reports are never deleted by this — they're
        kept indefinitely for trend history, which is exactly what the
        uploader opted into by naming their airframe.

        Returns the number of files deleted.
        """
        if not os.path.exists(self.DATA_DIR):
            return 0

        deleted = 0
        now = time.time()
        with self._lock:
            for filename in os.listdir(self.DATA_DIR):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(self.DATA_DIR, filename)
                try:
                    wrapper = self._read_wrapper(path)
                except Exception as e:
                    logger.error(f"Failed to read report {filename} during cleanup: {e}")
                    continue
                if wrapper is None:
                    continue
                if wrapper["airframe_label"]:
                    continue
                if (now - wrapper["created_at"]) > ttl_seconds:
                    try:
                        os.remove(path)
                        deleted += 1
                        report_id = filename[:-5]
                        self._store.pop(report_id, None)
                    except OSError as e:
                        logger.error(f"Failed to delete expired report {filename}: {e}")

        if deleted:
            logger.info(f"Cleaned up {deleted} expired untagged report(s).")
        return deleted

    def _read_wrapper(self, path: str) -> Optional[dict]:
        """
        Read a persisted report file. Handles both the current wrapper
        format ({"airframe_label", "created_at", "report"}) and the older
        format (a raw FlightMDReport dump with no wrapper), so reports
        persisted before airframe tagging shipped still load — treated as
        untagged and subject to normal expiry.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "report" in data and "report_id" not in data:
            return {
                "airframe_label": normalise_airframe_label(data.get("airframe_label")),
                "created_at": data.get("created_at", os.path.getmtime(path)),
                "report": data["report"],
            }
        # Legacy: raw report JSON with no wrapper.
        return {
            "airframe_label": None,
            "created_at": os.path.getmtime(path),
            "report": data,
        }

    def _load_from_disk(self, report_id: str) -> Optional[Job]:
        path = os.path.join(self.DATA_DIR, f"{report_id}.json")
        if not os.path.exists(path):
            return None
        try:
            wrapper = self._read_wrapper(path)
            if wrapper is None:
                return None
            report = FlightMDReport.model_validate(wrapper["report"])
            return Job(
                report_id=report_id,
                status=JobStatus.COMPLETE,
                progress=100,
                report=report,
                message="Analysis complete.",
                airframe_label=wrapper["airframe_label"],
                created_at=wrapper["created_at"],
            )
        except Exception as e:
            logger.error(f"Failed to load report {report_id} from disk: {e}")
            return None

    def _evict_expired(self) -> None:
        """Remove expired processing/failed jobs. Must be called inside lock."""
        expired = [
            rid for rid, job in self._store.items()
            if job.is_expired and job.status != JobStatus.COMPLETE
        ]
        for rid in expired:
            del self._store[rid]

    def _evict_oldest(self) -> None:
        """Evict the oldest job by created_at. Must be called inside lock."""
        if not self._store:
            return
        oldest_id = min(self._store, key=lambda rid: self._store[rid].created_at)
        del self._store[oldest_id]

    @property
    def job_count(self) -> int:
        with self._lock:
            return len(self._store)


# Global singleton — imported by routers
job_store = JobStore()
