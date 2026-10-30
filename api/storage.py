"""
Job store: job state and finished reports, one row each in the `reports` table.

Untagged reports expire after an hour (cleanup_expired runs from the app
lifespan). Reports tagged with an airframe label are kept for that airframe's
trend history; that's the opt-in. Job state lives in the database too, so
/status still answers after a restart: anything that was mid-analysis then
comes back as failed ("interrupted").
"""

import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from api import db
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)

REPORT_TTL_SECONDS = 3600

INTERRUPTED = "interrupted: the server restarted during the analysis, please upload the log again"


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
    eta_at: Optional[float] = None
    log_sha256: Optional[str] = None


MAX_AIRFRAME_LABEL_LEN = 40

# "/" can't be routed in /airframe/{label}/..., control chars just cause grief
_BAD_LABEL_CHARS = re.compile(r"[/\\\x00-\x1f\x7f]")

# report ids are uuid4 strings; anything else is never looked up
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def normalise_airframe_label(label: Optional[str]) -> Optional[str]:
    """Trimmed, length-capped label, or None for empty and unusable labels."""
    if label is None:
        return None
    label = label.strip()[:MAX_AIRFRAME_LABEL_LEN].strip()
    if not label or _BAD_LABEL_CHARS.search(label):
        return None
    return label


class JobStore:
    # queued + running at once; past this /analyse answers 503
    MAX_JOBS = 100
    PARSED_CACHE = 32

    def __init__(self):
        # finished reports never change, so parsed ones are kept for the next request.
        # Keyed by db path too, tests open a fresh db per case w/ the same ids
        self._parsed: "OrderedDict[tuple[str, str], FlightMDReport]" = OrderedDict()
        self._lock = threading.Lock()

    def create(
        self,
        report_id: str,
        airframe_label: Optional[str] = None,
        log_sha256: Optional[str] = None,
        brief_sha256: Optional[str] = None,
        log_format: Optional[str] = None,
    ) -> Job:
        now = time.time()
        label = normalise_airframe_label(airframe_label)
        with db.get().transaction() as c:
            running = c.execute("SELECT COUNT(*) FROM reports WHERE status = ?", (JobStatus.PROCESSING.value,)).fetchone()[0]
            if running >= self.MAX_JOBS:
                raise StoreFull()
            c.execute(
                "INSERT INTO reports (report_id, status, progress, message, airframe_label, log_format,"
                " log_sha256, brief_sha256, created_at, updated_at) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (report_id, JobStatus.PROCESSING.value, "Queued…", label, log_format, log_sha256,
                 brief_sha256, now, now),
            )
        return Job(report_id=report_id, message="Queued…", airframe_label=label, created_at=now,
                   log_sha256=log_sha256)

    def discard(self, report_id: str) -> None:
        db.get().execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
        self._forget(report_id)

    def get(self, report_id: str) -> Optional[Job]:
        if not REPORT_ID_RE.match(report_id):
            return None
        row = db.get().query_one("SELECT * FROM reports WHERE report_id = ?", (report_id,))
        if row is None:
            return None
        job = self._job(row)
        if job.status == JobStatus.COMPLETE:
            try:
                job.report = self._parse(report_id, row["report_json"])
            except ValueError as e:
                logger.error(f"could not load report {report_id}: {e}")
                return None
        return job

    def update_progress(self, report_id: str, progress: int, message: str = "",
                        eta_s: Optional[float] = None) -> None:
        now = time.time()
        eta_at = now + max(0.0, eta_s) if eta_s is not None else None
        db.get().execute(
            "UPDATE reports SET progress = ?, message = ?, eta_at = ?, updated_at = ?"
            " WHERE report_id = ? AND status = ?",
            (min(100, max(0, int(progress))), message, eta_at, now, report_id, JobStatus.PROCESSING.value),
        )

    def complete(self, report_id: str, report: FlightMDReport) -> None:
        now = time.time()
        body = report.model_dump_json()
        sha = getattr(report.metadata, "log_sha256", None)
        # upsert: a job that was discarded meanwhile still gets its report saved, untagged
        db.get().execute(
            "INSERT INTO reports (report_id, status, progress, message, log_sha256, created_at, updated_at, report_json)"
            " VALUES (?, ?, 100, ?, ?, ?, ?, ?)"
            " ON CONFLICT (report_id) DO UPDATE SET status = excluded.status, progress = 100,"
            " message = excluded.message, eta_at = NULL, error = NULL, updated_at = excluded.updated_at,"
            " report_json = excluded.report_json,"
            " log_sha256 = COALESCE(reports.log_sha256, excluded.log_sha256)",
            (report_id, JobStatus.COMPLETE.value, "Analysis complete.", sha, now, now, body),
        )
        self._forget(report_id)

    def fail(self, report_id: str, error: str) -> None:
        db.get().execute(
            "UPDATE reports SET status = ?, error = ?, message = ?, eta_at = NULL, updated_at = ? WHERE report_id = ?",
            (JobStatus.FAILED.value, error, f"Analysis failed: {error}", time.time(), report_id),
        )

    def status_summary(self, report_id: str) -> dict:
        if not REPORT_ID_RE.match(report_id):
            return {"status": "not_found"}
        row = db.get().query_one(
            "SELECT status, progress, message, error, eta_at FROM reports WHERE report_id = ?", (report_id,)
        )
        if row is None:
            return {"status": "not_found"}
        eta = None
        if row["status"] == JobStatus.PROCESSING.value and row["eta_at"] is not None:
            eta = round(max(0.0, row["eta_at"] - time.time()), 1)
        result = {
            "status": row["status"],
            "progress": row["progress"],
            "message": row["message"],
            "eta_seconds": eta,
        }
        if row["error"]:
            result["error"] = row["error"]
        return result

    def find_recent_duplicate(
        self,
        log_sha256: str,
        airframe_label: Optional[str],
        brief_sha256: Optional[str],
        max_age_s: float = REPORT_TTL_SECONDS,
    ) -> Optional[tuple[str, str]]:
        """(report_id, status) of a running or finished analysis of the same bytes,
        same airframe tag and same brief hash, started within max_age_s."""
        row = db.get().query_one(
            "SELECT report_id, status FROM reports"
            " WHERE log_sha256 = ? AND status IN (?, ?) AND created_at >= ?"
            " AND COALESCE(airframe_label, '') = ? AND COALESCE(brief_sha256, '') = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (log_sha256, JobStatus.PROCESSING.value, JobStatus.COMPLETE.value, time.time() - max_age_s,
             airframe_label or "", brief_sha256 or ""),
        )
        return (row["report_id"], row["status"]) if row else None

    def list_by_airframe_with_created_at(self, airframe_label: str) -> list[tuple[float, FlightMDReport]]:
        """(created_at, report) for every finished report tagged with this airframe, oldest first.

        The same log uploaded twice counts once (the first upload), so trend
        points and maintenance hours aren't doubled.
        """
        airframe_label = normalise_airframe_label(airframe_label)
        if not airframe_label:
            return []
        rows = db.get().query(
            "SELECT report_id, created_at, log_sha256, report_json FROM reports"
            " WHERE airframe_label = ? AND status = ? ORDER BY created_at, report_id",
            (airframe_label, JobStatus.COMPLETE.value),
        )
        seen = set()
        out = []
        for r in rows:
            if r["log_sha256"]:
                if r["log_sha256"] in seen:
                    continue
                seen.add(r["log_sha256"])
            try:
                out.append((r["created_at"], self._parse(r["report_id"], r["report_json"])))
            except ValueError as e:
                logger.error(f"skipping unreadable report {r['report_id']}: {e}")
        return out

    def list_by_airframe(self, airframe_label: str) -> list[FlightMDReport]:
        return [r for _, r in self.list_by_airframe_with_created_at(airframe_label)]

    def cleanup_expired(self, ttl_seconds: int = REPORT_TTL_SECONDS) -> list[str]:
        """Delete untagged reports and failed jobs older than ttl_seconds. Returns their ids."""
        cutoff = time.time() - ttl_seconds
        with db.get().transaction() as c:
            rows = c.execute(
                "SELECT report_id FROM reports WHERE created_at < ? AND"
                " ((status = ? AND airframe_label IS NULL) OR status = ?)",
                (cutoff, JobStatus.COMPLETE.value, JobStatus.FAILED.value),
            ).fetchall()
            ids = [r[0] for r in rows]
            c.executemany("DELETE FROM reports WHERE report_id = ?", [(i,) for i in ids])
        for report_id in ids:
            self._forget(report_id)
        if ids:
            logger.info(f"Cleaned up {len(ids)} expired report(s).")
        return ids

    def interrupt_running(self) -> int:
        """At startup: whatever was mid-analysis died with the old process."""
        n = db.get().execute(
            "UPDATE reports SET status = ?, error = ?, message = ?, eta_at = NULL, updated_at = ? WHERE status = ?",
            (JobStatus.FAILED.value, INTERRUPTED, f"Analysis failed: {INTERRUPTED}", time.time(),
             JobStatus.PROCESSING.value),
        )
        if n:
            logger.warning(f"{n} analysis job(s) interrupted by the restart")
        return n

    def fail_stale(self, max_idle_s: float) -> int:
        """Fail jobs with no progress for max_idle_s (a worker that was killed outright)."""
        return db.get().execute(
            "UPDATE reports SET status = ?, error = ?, message = ?, eta_at = NULL, updated_at = ?"
            " WHERE status = ? AND updated_at < ?",
            (JobStatus.FAILED.value, INTERRUPTED, f"Analysis failed: {INTERRUPTED}", time.time(),
             JobStatus.PROCESSING.value, time.time() - max_idle_s),
        )

    @property
    def job_count(self) -> int:
        row = db.get().query_one("SELECT COUNT(*) FROM reports WHERE status = ?", (JobStatus.PROCESSING.value,))
        return row[0]

    def _job(self, row) -> Job:
        return Job(
            report_id=row["report_id"],
            status=JobStatus(row["status"]),
            progress=row["progress"],
            message=row["message"],
            error=row["error"],
            airframe_label=row["airframe_label"],
            created_at=row["created_at"],
            eta_at=row["eta_at"],
            log_sha256=row["log_sha256"],
        )

    def _parse(self, report_id: str, body: Optional[str]) -> FlightMDReport:
        key = (db.get().path, report_id)
        with self._lock:
            hit = self._parsed.get(key)
            if hit is not None:
                self._parsed.move_to_end(key)
                return hit
        if not body:
            raise ValueError("no report body")
        report = FlightMDReport.model_validate_json(body)
        with self._lock:
            self._parsed[key] = report
            while len(self._parsed) > self.PARSED_CACHE:
                self._parsed.popitem(last=False)
        return report

    def _forget(self, report_id: str) -> None:
        with self._lock:
            self._parsed.pop((db.get().path, report_id), None)


job_store = JobStore()
