"""
One-time import of the pre-database layout (one JSON file per report, per
airframe and per contribution, under api/data/) into SQLite.

Runs at startup. A directory that has been imported is renamed to
"<name>.imported" rather than deleted, so the originals stay on disk until
the owner removes them, and the next start doesn't import it again. Files
that won't parse are logged and left in the renamed directory.
"""

import json
import logging
import os
import re
import time

from api import blobs, db
from api.airframe_store import AirframeConfig
from api.storage import REPORT_ID_RE, JobStatus, normalise_airframe_label
from api.training_data_store import CONTRIBUTION_ID_RE, anonymise, file_sha256
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)

# where the JSON stores used to live
LEGACY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))

# airframe files named "<slug>-<16 hex>.json" are newer than bare "<slug>.json" ones
_HASHED_NAME = re.compile(r"-[0-9a-f]{16}\.json$")


def import_legacy(roots: list[str]) -> dict:
    """Import every legacy store found under the given roots. Returns counts per kind."""
    counts = {"reports": 0, "airframes": 0, "contributions": 0}
    seen = set()
    for root in roots:
        root = os.path.abspath(root)
        if root in seen:
            continue
        seen.add(root)
        for kind, fn in (("reports", _import_reports), ("airframes", _import_airframes),
                         ("training_contributions", _import_contributions)):
            path = os.path.join(root, kind)
            if not os.path.isdir(path):
                continue
            n = fn(path)
            counts["contributions" if kind == "training_contributions" else kind] += n
            _retire(path)
            logger.info(f"imported {n} legacy {kind} from {path}")
    return counts


def _retire(path: str) -> None:
    dest = path + ".imported"
    if os.path.exists(dest):
        dest = f"{path}.imported-{int(time.time())}"
    os.rename(path, dest)


def _json_files(path: str) -> list[str]:
    return sorted(f for f in os.listdir(path) if f.endswith(".json") and not f.startswith(".tmp-"))


def _read(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _import_reports(path: str) -> int:
    database = db.get()
    n = 0
    for name in _json_files(path):
        report_id = name[:-5]
        full = os.path.join(path, name)
        if not REPORT_ID_RE.match(report_id):
            logger.warning(f"legacy report {name}: unusable id, skipped")
            continue
        try:
            data = _read(full)
            if "report" in data and "report_id" not in data:
                label = normalise_airframe_label(data.get("airframe_label"))
                created_at = data.get("created_at") or os.path.getmtime(full)
                body = data["report"]
            else:
                # files from before airframe tagging are a bare report dump
                label, created_at, body = None, os.path.getmtime(full), data
            report = FlightMDReport.model_validate(body)
        except (OSError, ValueError, KeyError) as e:
            logger.error(f"legacy report {name} not imported: {e}")
            continue

        report.report_id = report_id
        sha = getattr(report.metadata, "log_sha256", None)
        n += database.execute(
            "INSERT INTO reports (report_id, status, progress, message, airframe_label, log_sha256,"
            " created_at, updated_at, report_json) VALUES (?, ?, 100, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (report_id) DO NOTHING",
            (report_id, JobStatus.COMPLETE.value, "Analysis complete.", label, sha, created_at, time.time(),
             report.model_dump_json()),
        )
    return n


def _import_airframes(path: str) -> int:
    database = db.get()
    # hashed names first: when both files exist for a label the hashed one is current
    names = sorted(_json_files(path), key=lambda f: 0 if _HASHED_NAME.search(f) else 1)
    n = 0
    for name in names:
        full = os.path.join(path, name)
        try:
            config = AirframeConfig.from_dict(_read(full))
            mtime = os.path.getmtime(full)
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error(f"legacy airframe {name} not imported: {e}")
            continue
        n += database.execute(
            "INSERT INTO airframes (label, token_hash, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (label) DO NOTHING",
            (config.airframe_label, config.token_hash, json.dumps(config.to_dict()), mtime, mtime),
        )
    return n


def _import_contributions(path: str) -> int:
    database = db.get()
    store = blobs.get()
    n = 0
    for name in _json_files(path):
        contribution_id = name[:-5]
        if not CONTRIBUTION_ID_RE.match(contribution_id):
            continue
        logs = [f for f in os.listdir(path) if f.startswith(contribution_id) and not f.endswith(".json")]
        if len(logs) != 1:
            logger.error(f"legacy contribution {contribution_id}: expected one log file, found {len(logs)}")
            continue
        log_path = os.path.join(path, logs[0])
        try:
            meta = _read(os.path.join(path, name))
            report = FlightMDReport.model_validate(meta["report"])
            sha = file_sha256(log_path)
        except (OSError, ValueError, KeyError) as e:
            logger.error(f"legacy contribution {contribution_id} not imported: {e}")
            continue

        key = logs[0]
        store.put(key, log_path)
        n += database.execute(
            "INSERT INTO contributions (contribution_id, log_sha256, log_format, blob_key, size_bytes,"
            " contributed_at, report_json) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (contribution_id) DO NOTHING",
            (contribution_id, sha, meta.get("log_format", "unknown"), key, os.path.getsize(log_path),
             meta.get("contributed_at") or os.path.getmtime(log_path), json.dumps(anonymise(report))),
        )
    return n
