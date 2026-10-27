"""
Opt-in dataset: logs people chose to contribute, plus a stripped copy of
their report.

Nothing lands here unless the uploader ticks "contribute". No name, account,
IP or original filename is stored, and the report copy loses its filename,
place name and GPS track. The raw log itself still holds whatever positions
the autopilot recorded; we keep the file as uploaded, in the blob store.
Identical logs are stored once. The contribution id goes back to the uploader
and is what DELETE /dataset/{id} takes to withdraw it.
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from api import blobs, db
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)

_STRIP_META = ("location_name", "gps_path", "gps_path_wind_speed_ms", "gps_path_hdop")

CONTRIBUTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class ContributionStats:
    count: int
    total_bytes: int


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def contribution_id_for(log_sha256: str) -> str:
    # content hash as the id: the same log contributed twice is stored once
    return log_sha256[:32]


def anonymise(report: FlightMDReport) -> dict:
    data = report.model_dump(mode="json")
    data["file_name"] = ""
    data["report_id"] = ""
    meta = data.get("metadata") or {}
    for key in _STRIP_META:
        meta[key] = None
    return data


class TrainingDataStore:
    def save(self, log_path: str, file_suffix: str, log_format: str, report: FlightMDReport,
             log_sha256: Optional[str] = None) -> str:
        """Store the log and the stripped report. Returns the contribution id."""
        sha = log_sha256 or file_sha256(log_path)
        contribution_id = contribution_id_for(sha)
        database = db.get()
        if database.query_one("SELECT 1 FROM contributions WHERE contribution_id = ?", (contribution_id,)):
            return contribution_id

        # blob first: a row without its log would be worse than a stray log
        key = f"{contribution_id}{file_suffix}"
        blobs.get().put(key, log_path)
        database.execute(
            "INSERT INTO contributions (contribution_id, log_sha256, log_format, blob_key, size_bytes,"
            " contributed_at, report_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (contribution_id) DO NOTHING",
            (contribution_id, sha, log_format, key, os.path.getsize(log_path), time.time(),
             json.dumps(anonymise(report))),
        )
        logger.info(f"dataset contribution {contribution_id} saved ({log_format})")
        return contribution_id

    def delete(self, contribution_id: str) -> bool:
        """Withdraw a contribution. False if there was nothing under that id."""
        database = db.get()
        row = database.query_one("SELECT blob_key FROM contributions WHERE contribution_id = ?", (contribution_id,))
        if row is None:
            return False
        # log before row, so a failed delete leaves a row to retry against
        blobs.get().delete(row["blob_key"])
        database.execute("DELETE FROM contributions WHERE contribution_id = ?", (contribution_id,))
        logger.info(f"dataset contribution {contribution_id} withdrawn")
        return True

    def stats(self) -> ContributionStats:
        row = db.get().query_one("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM contributions")
        return ContributionStats(count=row[0], total_bytes=row[1])


training_data_store = TrainingDataStore()
