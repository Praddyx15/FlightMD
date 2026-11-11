"""
Tune, fly, verify: parameter changes someone applied after a flight, and
whether the next flight of the same airframe shows them working.

A change is recorded against the report it came from. Its verification
compares that report with the first tagged report of the same airframe
uploaded after the change was recorded, looking only at findings whose
`params` touch a changed parameter, plus the overall and module scores.
It is computed when read, and stored again whenever a tagged report lands.
"""

import json
import logging
import time
import uuid
from typing import Optional

from api import db
from api.storage import job_store
from flightmd_core.models.findings import FlightMDReport

logger = logging.getLogger(__name__)

# score moves smaller than this (points) count as noise
SCORE_TOLERANCE = 2.0


def pending() -> dict:
    return {
        "status": "pending",
        "next_report_id": None,
        "findings_resolved": [],
        "findings_new": [],
        "metric_deltas": {},
    }


def _finding_params(f) -> set[str]:
    # the model fills `params` from param_changes too, so pre-1.7 reports match as well
    return {n.upper() for n in f.params}


def _finding_key(f) -> str:
    # titles carry values ("... at 1.1 Hz"), kind doesn't
    return f.kind or f.title


def _module_score(ar) -> Optional[float]:
    if ar.skipped or not ar.assessed:
        return None
    return ar.health_score


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def verify(before: FlightMDReport, after: Optional[FlightMDReport], changed: set[str]) -> dict:
    if after is None:
        return pending()
    changed = {n.upper() for n in changed}

    rel_before = [f for f in before.findings if _finding_params(f) & changed]
    rel_after = [f for f in after.findings if _finding_params(f) & changed]
    keys_before = {_finding_key(f) for f in before.findings}
    keys_after = {_finding_key(f) for f in after.findings}

    resolved = _unique([f.title for f in rel_before if _finding_key(f) not in keys_after])
    new = _unique([f.title for f in rel_after if _finding_key(f) not in keys_before])

    # modules that raised a relevant finding in either flight
    rel_ids = {f.id for f in rel_before + rel_after}
    rel_categories = {f.category.value for f in rel_before + rel_after}
    modules = set()
    for report in (before, after):
        for ar in report.analyser_results:
            if ar.analyser in rel_categories or any(f.id in rel_ids for f in ar.findings):
                modules.add(ar.analyser)

    deltas = {"overall_score": round(after.overall_score - before.overall_score, 2)}
    scores_before = {ar.analyser: _module_score(ar) for ar in before.analyser_results}
    scores_after = {ar.analyser: _module_score(ar) for ar in after.analyser_results}
    module_deltas = {}
    for name in sorted(modules):
        a, b = scores_before.get(name), scores_after.get(name)
        if a is not None and b is not None:
            module_deltas[f"module.{name}"] = round(b - a, 2)
    deltas.update(module_deltas)

    # the overall score moves with everything else in the flight, so it only
    # decides when no module tied to the change could be compared
    moves = list(module_deltas.values()) or [deltas["overall_score"]]
    up = bool(resolved) or any(d >= SCORE_TOLERANCE for d in moves)
    down = bool(new) or any(d <= -SCORE_TOLERANCE for d in moves)
    if up and down:
        status = "mixed"
    elif up:
        status = "improved"
    elif down:
        status = "worse"
    else:
        status = "unchanged"

    return {
        "status": status,
        "next_report_id": after.report_id,
        "findings_resolved": resolved,
        "findings_new": new,
        "metric_deltas": deltas,
    }


class ParamChangeStore:
    def add(self, airframe_label: str, report_id: str, changes: list[dict], applied_by: str,
            note: Optional[str] = None) -> dict:
        row = {
            "id": uuid.uuid4().hex,
            "airframe_label": airframe_label,
            "report_id": report_id,
            "changes": changes,
            "applied_by": applied_by,
            "note": note,
            "created_at": time.time(),
        }
        db.get().execute(
            "INSERT INTO param_changes (id, airframe_label, report_id, changes_json, applied_by, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row["id"], airframe_label, report_id, json.dumps(changes), applied_by, note, row["created_at"]),
        )
        return row

    def for_airframe(self, airframe_label: str) -> list[dict]:
        """Newest first."""
        rows = db.get().query(
            "SELECT * FROM param_changes WHERE airframe_label = ? ORDER BY created_at DESC, id",
            (airframe_label,),
        )
        return [
            {
                "id": r["id"],
                "airframe_label": r["airframe_label"],
                "report_id": r["report_id"],
                "changes": json.loads(r["changes_json"]),
                "applied_by": r["applied_by"],
                "note": r["note"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def save_verify(self, change_id: str, result: dict) -> None:
        db.get().execute("UPDATE param_changes SET verify_json = ? WHERE id = ?", (json.dumps(result), change_id))


param_change_store = ParamChangeStore()


def with_verification(airframe_label: str, changes: list[dict]) -> list[dict]:
    """The changes with a fresh `verify` block each. Loads the airframe's flights once."""
    if not changes:
        return []
    flights = job_store.list_by_airframe_with_created_at(airframe_label)
    by_id = {r.report_id: r for _, r in flights}
    out = []
    for ch in changes:
        before = by_id.get(ch["report_id"])
        if before is None:
            # the source flight is gone (or was a duplicate upload): nothing to compare with
            out.append({**ch, "verify": pending()})
            continue
        after = next((r for created_at, r in flights
                      if created_at > ch["created_at"] and r.report_id != before.report_id), None)
        names = {c["name"] for c in ch["changes"]}
        out.append({**ch, "verify": verify(before, after, names)})
    return out


def refresh_pending(airframe_label: str) -> int:
    """After a tagged report lands: store the verification of changes that were still pending."""
    pending = []
    for r in db.get().query(
        "SELECT id, verify_json FROM param_changes WHERE airframe_label = ?", (airframe_label,)
    ):
        if r["verify_json"] is None or json.loads(r["verify_json"]).get("status") == "pending":
            pending.append(r["id"])
    if not pending:
        return 0
    changes = [ch for ch in param_change_store.for_airframe(airframe_label) if ch["id"] in pending]
    n = 0
    for ch in with_verification(airframe_label, changes):
        param_change_store.save_verify(ch["id"], ch["verify"])
        if ch["verify"]["status"] != "pending":
            n += 1
            logger.info(f"change {ch['id']} on its next flight: {ch['verify']['status']}")
    return n
