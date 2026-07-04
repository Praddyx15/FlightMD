"""
In-memory job store (Phase 1).

Phase 3: swap this module for a Redis/Supabase-backed implementation.
The interface (get_job, set_job, update_progress, etc.) stays the same.

Limits:
  - Max 100 concurrent jobs (free tier constraint)
  - 1-hour TTL per job
  - LRU eviction when at capacity
"""

import time
import threading
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

from flightmd_core.models.findings import FlightMDReport


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
    Thread-safe in-memory job store with LRU eviction.
    """
    MAX_JOBS = 100

    def __init__(self):
        self._store: dict[str, Job] = {}
        self._lock  = threading.Lock()

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
        """Retrieve a job by ID. Returns None if not found or expired."""
        with self._lock:
            job = self._store.get(report_id)
            if job is None:
                return None
            if job.is_expired:
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
        """Mark job as complete and attach the finished report."""
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.status   = JobStatus.COMPLETE
                job.progress = 100
                job.report   = report
                job.message  = "Analysis complete."

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

    def _evict_expired(self) -> None:
        """Remove expired jobs. Must be called inside lock."""
        expired = [rid for rid, job in self._store.items() if job.is_expired]
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
