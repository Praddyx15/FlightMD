"""
Job store: in-memory job state plus one JSON file per finished report.

Untagged reports expire after an hour (cleanup_expired_disk_reports runs from
the app lifespan). Reports tagged with an airframe label are kept for that
airframe's trend history; that's the opt-in. On Render's free plan the disk is
ephemeral, so "kept" really means "until the next deploy or restart".
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from api.fs import write_json_atomic
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETE   = "complete"
    FAILED     = "failed"


class StoreFull(Exception):
    pass


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
    ttl_seconds: int = 3600   # only enforced for untagged reports

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


MAX_AIRFRAME_LABEL_LEN = 40

# "/" can't be routed in /airframe/{label}/..., control chars just cause grief
_BAD_LABEL_CHARS = re.compile(r"[/\\\x00-\x1f\x7f]")

# report ids are uuid4 strings; anything else never touches the disk
_REPORT_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def normalise_airframe_label(label: Optional[str]) -> Optional[str]:
    """Trimmed, length-capped label, or None for empty and unusable labels."""
    if label is None:
        return None
    label = label.strip()[:MAX_AIRFRAME_LABEL_LEN].strip()
    if not label or _BAD_LABEL_CHARS.search(label):
        return None
    return label


class JobStore:
    MAX_JOBS = 100
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "reports"))

    def __init__(self):
        self._store: dict[str, Job] = {}
        self._lock  = threading.Lock()
        os.makedirs(self.DATA_DIR, exist_ok=True)

    def create(self, report_id: str, airframe_label: Optional[str] = None) -> Job:
        with self._lock:
            self._evict_expired()
            if len(self._store) >= self.MAX_JOBS:
                self._evict_oldest()
            job = Job(report_id=report_id, airframe_label=normalise_airframe_label(airframe_label))
            self._store[report_id] = job
            return job

    def discard(self, report_id: str) -> None:
        with self._lock:
            self._store.pop(report_id, None)

    def get(self, report_id: str) -> Optional[Job]:
        with self._lock:
            job = self._store.get(report_id)
            if job is not None:
                # finished reports stay until the disk sweep removes them
                if job.is_expired and job.status != JobStatus.COMPLETE:
                    del self._store[report_id]
                    return None
                return job

        loaded = self._load_from_disk(report_id)
        if loaded is None:
            return None
        with self._lock:
            return self._store.setdefault(report_id, loaded)

    def update_progress(self, report_id: str, progress: int, message: str = "") -> None:
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.progress = min(100, max(0, progress))
                job.message  = message

    def complete(self, report_id: str, report: FlightMDReport) -> None:
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.status   = JobStatus.COMPLETE
                job.progress = 100
                job.report   = report
                job.message  = "Analysis complete."
            airframe_label = job.airframe_label if job else None
            created_at     = job.created_at if job else time.time()

        wrapper = {
            "airframe_label": airframe_label,
            "created_at": created_at,
            "report": report.model_dump(mode="json"),
        }
        try:
            write_json_atomic(self._path(report_id), wrapper)
        except OSError as e:
            # the report is still served from memory, it just won't survive a restart
            logger.error(f"could not persist report {report_id}: {e}")

    def fail(self, report_id: str, error: str) -> None:
        with self._lock:
            job = self._store.get(report_id)
            if job:
                job.status = JobStatus.FAILED
                job.error  = error
                job.message = f"Analysis failed: {error}"

    def status_summary(self, report_id: str) -> dict:
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

    def list_by_airframe_with_created_at(self, airframe_label: str) -> list[tuple[float, FlightMDReport]]:
        """(created_at, report) for every report tagged with this airframe, oldest first."""
        airframe_label = normalise_airframe_label(airframe_label)
        if not airframe_label:
            return []

        # TODO this reads every report file per call; fine until there's a real db
        reports = []
        for filename in self._report_files():
            try:
                wrapper = self._read_wrapper(os.path.join(self.DATA_DIR, filename))
                if wrapper["airframe_label"] != airframe_label:
                    continue
                report = FlightMDReport.model_validate(wrapper["report"])
            except (OSError, ValueError) as e:
                logger.error(f"skipping unreadable report {filename}: {e}")
                continue
            reports.append((wrapper["created_at"], report))

        reports.sort(key=lambda pair: pair[0])
        return reports

    def list_by_airframe(self, airframe_label: str) -> list[FlightMDReport]:
        return [r for _, r in self.list_by_airframe_with_created_at(airframe_label)]

    def cleanup_expired_disk_reports(self, ttl_seconds: int = 3600) -> int:
        """Delete untagged report files older than ttl_seconds. Returns how many went."""
        deleted = 0
        now = time.time()
        for filename in self._report_files():
            path = os.path.join(self.DATA_DIR, filename)
            try:
                wrapper = self._read_wrapper(path)
            except (OSError, ValueError) as e:
                logger.error(f"cleanup could not read {filename}: {e}")
                continue
            if wrapper["airframe_label"] or now - wrapper["created_at"] <= ttl_seconds:
                continue
            try:
                os.remove(path)
            except OSError as e:
                logger.error(f"could not delete expired report {filename}: {e}")
                continue
            deleted += 1
            with self._lock:
                self._store.pop(filename[:-5], None)

        if deleted:
            logger.info(f"Cleaned up {deleted} expired untagged report(s).")
        return deleted

    @property
    def job_count(self) -> int:
        with self._lock:
            return len(self._store)

    def _path(self, report_id: str) -> str:
        return os.path.join(self.DATA_DIR, f"{report_id}.json")

    def _report_files(self) -> list[str]:
        try:
            return [f for f in os.listdir(self.DATA_DIR) if f.endswith(".json")]
        except FileNotFoundError:
            return []

    def _read_wrapper(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "report" in data and "report_id" not in data:
            return {
                "airframe_label": normalise_airframe_label(data.get("airframe_label")),
                "created_at": data.get("created_at", os.path.getmtime(path)),
                "report": data["report"],
            }
        # files from before airframe tagging are a bare report dump, treat as untagged
        return {
            "airframe_label": None,
            "created_at": os.path.getmtime(path),
            "report": data,
        }

    def _load_from_disk(self, report_id: str) -> Optional[Job]:
        if not _REPORT_ID_RE.match(report_id):
            return None
        path = self._path(report_id)
        if not os.path.exists(path):
            return None
        try:
            wrapper = self._read_wrapper(path)
            report = FlightMDReport.model_validate(wrapper["report"])
        except (OSError, ValueError) as e:
            logger.error(f"could not load report {report_id}: {e}")
            return None
        return Job(
            report_id=report_id,
            status=JobStatus.COMPLETE,
            progress=100,
            report=report,
            message="Analysis complete.",
            airframe_label=wrapper["airframe_label"],
            created_at=wrapper["created_at"],
        )

    def _evict_expired(self) -> None:
        expired = [
            rid for rid, job in self._store.items()
            if job.is_expired and job.status != JobStatus.COMPLETE
        ]
        for rid in expired:
            del self._store[rid]

    def _evict_oldest(self) -> None:
        # never drop a running job: complete() would then save it untagged
        # and /status would 404 halfway through
        idle = [rid for rid, job in self._store.items() if job.status != JobStatus.PROCESSING]
        if not idle:
            raise StoreFull()
        oldest = min(idle, key=lambda rid: self._store[rid].created_at)
        del self._store[oldest]


job_store = JobStore()
