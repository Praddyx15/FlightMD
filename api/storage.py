"""
In-memory job store (Phase 1).

Phase 3: swap this module for a Redis/Supabase-backed implementation.
The interface (get_job, set_job, update_progress, etc.) stays the same.

Limits:
  - Max 100 concurrent jobs (free tier constraint)
  - 1-hour TTL per job
  - LRU eviction when at capacity
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
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 3600   # 1 hour

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class JobStore:
    """
    Thread-safe in-memory job store with disk-backed persistence for complete reports.
    """
    MAX_JOBS = 100
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "reports"))

    def __init__(self):
        self._store: dict[str, Job] = {}
        self._lock  = threading.Lock()
        os.makedirs(self.DATA_DIR, exist_ok=True)

    def create(self, report_id: str) -> Job:
        """Create a new job and store it. Evict oldest if at capacity."""
        with self._lock:
            self._evict_expired()
            if len(self._store) >= self.MAX_JOBS:
                self._evict_oldest()
            job = Job(report_id=report_id)
            self._store[report_id] = job
            return job

    def get(self, report_id: str) -> Optional[Job]:
        """Retrieve a job by ID. Checks memory first, then loads from disk if missing."""
        with self._lock:
            job = self._store.get(report_id)
            if job is None:
                # Try reading from disk
                path = os.path.join(self.DATA_DIR, f"{report_id}.json")
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        report = FlightMDReport.model_validate(data)
                        job = Job(
                            report_id=report_id,
                            status=JobStatus.COMPLETE,
                            progress=100,
                            report=report,
                            message="Analysis complete.",
                        )
                        self._store[report_id] = job
                        return job
                    except Exception as e:
                        logger.error(f"Failed to load report {report_id} from disk: {e}")
                        return None
                return None

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

            # Save to disk
            try:
                path = os.path.join(self.DATA_DIR, f"{report_id}.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(report.model_dump_json())
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

        # Read directory listing without blocking key operations if possible,
        # but keep it thread-safe.
        with self._lock:
            for filename in os.listdir(self.DATA_DIR):
                if filename.endswith(".json"):
                    report_id = filename[:-5]
                    path = os.path.join(self.DATA_DIR, filename)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        meta = data.get("metadata", {})
                        weather = meta.get("weather", {})
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
                            "created_at": os.path.getmtime(path),
                        })
                    except Exception as e:
                        logger.error(f"Failed to read report {filename} for summary: {e}")

        # Sort newest first
        summaries.sort(key=lambda x: x["created_at"], reverse=True)
        return summaries

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
