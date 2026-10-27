"""
Opt-in dataset: logs people chose to contribute, plus a stripped copy of
their report.

Nothing lands here unless the uploader ticks "contribute". No name, account,
IP or original filename is stored, and the report copy loses its filename,
place name and GPS track. The raw log itself still holds whatever positions
the autopilot recorded; we keep the file as uploaded.
Contributions aren't auto-deleted. Identical logs are only stored once.
"""

import hashlib
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass

from api.fs import write_json_atomic
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)

_STRIP_META = ("location_name", "gps_path", "gps_path_wind_speed_ms", "gps_path_hdop")


@dataclass
class ContributionStats:
    count: int
    total_bytes: int


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def anonymise(report: FlightMDReport) -> dict:
    data = report.model_dump(mode="json")
    data["file_name"] = ""
    data["report_id"] = ""
    meta = data.get("metadata") or {}
    for key in _STRIP_META:
        meta[key] = None
    return data


class TrainingDataStore:
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "training_contributions"))

    def __init__(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)

    def save(self, log_path: str, file_suffix: str, log_format: str, report: FlightMDReport) -> str:
        """Copy the log in and write the stripped report next to it. Returns the contribution id."""
        # content hash as the id: the same log contributed twice is stored once
        contribution_id = _sha256(log_path)[:32]
        dest = os.path.join(self.DATA_DIR, f"{contribution_id}{file_suffix}")
        meta_path = os.path.join(self.DATA_DIR, f"{contribution_id}.json")
        if os.path.exists(dest) and os.path.exists(meta_path):
            return contribution_id

        fd, tmp = tempfile.mkstemp(dir=self.DATA_DIR, prefix=".tmp-")
        os.close(fd)
        try:
            shutil.copyfile(log_path, tmp)
            os.replace(tmp, dest)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

        write_json_atomic(meta_path, {
            "contribution_id": contribution_id,
            "log_format": log_format,
            "contributed_at": time.time(),
            "report": anonymise(report),
        })
        logger.info(f"dataset contribution {contribution_id} saved ({log_format})")
        return contribution_id

    def stats(self) -> ContributionStats:
        """Count and size of the logs, not their JSON sidecars."""
        count = 0
        total_bytes = 0
        try:
            names = os.listdir(self.DATA_DIR)
        except FileNotFoundError:
            return ContributionStats(count=0, total_bytes=0)
        for name in names:
            if name.endswith(".json") or name.startswith(".tmp-"):
                continue
            count += 1
            try:
                total_bytes += os.path.getsize(os.path.join(self.DATA_DIR, name))
            except OSError:
                pass   # deleted between listdir and getsize
        return ContributionStats(count=count, total_bytes=total_bytes)


training_data_store = TrainingDataStore()
