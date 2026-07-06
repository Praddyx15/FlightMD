"""
Opt-in store for flight logs contributed to a growing dataset — the raw
log file plus the FlightMD report generated from it.

This is entirely separate from JobStore's ephemeral per-flight storage:
- Nothing lands here unless the uploader explicitly checks "contribute
  this log anonymously" at upload time. Default is off.
- What "anonymous" means here: no name, account, email, or IP address is
  ever attached to a contribution — only the log file itself and its
  analysis output. It does NOT mean the flight's own recorded GPS
  coordinates are stripped; a flight log inherently contains wherever it
  was flown, same as any log on PX4's own public review database.
- Contributions are never auto-deleted (unlike the 1-hour ephemeral
  default) — that's the entire point of a growing dataset.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass

from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)


@dataclass
class ContributionStats:
    count: int
    total_bytes: int


class TrainingDataStore:
    """Append-only store for contributed (log, report) pairs."""

    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "training_contributions"))

    def __init__(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)

    def save(
        self,
        content: bytes,
        file_suffix: str,
        log_format: str,
        report: FlightMDReport,
    ) -> str:
        """
        Persist a contributed log + its report. Returns the generated
        contribution_id. Deliberately does not take a report_id, uploader
        identity, or original filename — those aren't part of what gets
        stored for an anonymous contribution.
        """
        contribution_id = str(uuid.uuid4())
        log_path = os.path.join(self.DATA_DIR, f"{contribution_id}{file_suffix}")
        meta_path = os.path.join(self.DATA_DIR, f"{contribution_id}.json")

        with open(log_path, "wb") as f:
            f.write(content)

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "contribution_id": contribution_id,
                    "log_format": log_format,
                    "contributed_at": time.time(),
                    "report": report.model_dump(mode="json"),
                },
                f,
            )

        logger.info(f"Training contribution {contribution_id} saved ({log_format}, {len(content)} bytes)")
        return contribution_id

    def stats(self) -> ContributionStats:
        """Count and total size of contributed logs (not the JSON sidecars)."""
        if not os.path.exists(self.DATA_DIR):
            return ContributionStats(count=0, total_bytes=0)

        count = 0
        total_bytes = 0
        for filename in os.listdir(self.DATA_DIR):
            if filename.endswith(".json"):
                continue
            count += 1
            try:
                total_bytes += os.path.getsize(os.path.join(self.DATA_DIR, filename))
            except OSError:
                pass
        return ContributionStats(count=count, total_bytes=total_bytes)


# Global singleton — imported by routers
training_data_store = TrainingDataStore()
