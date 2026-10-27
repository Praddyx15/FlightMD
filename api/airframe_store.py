"""
Per-airframe settings that outlive any single flight: maintenance log,
pre-flight checklist, alert rules and webhook.

There's no "register an airframe" step. A label exists once someone tags a
flight with it or writes its config, and the first of those claims it: the
caller gets a random airframe token back once, and every later read or write
has to present it. Only a sha256 of the token is stored.

Lives in the `airframes` table (api/db.py); the old one-JSON-file-per-airframe
layout is imported once at startup by api/legacy_import.py.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from api import db

logger = logging.getLogger(__name__)

VALID_COMPARISONS = ("lt", "gt")

# "overall_score", "module.<analyser>" or "<analyser>.<key_metric>"
METRIC_NAME_RE = re.compile(r"^[a-zA-Z0-9_.]{1,64}$")

_UNSET = object()


@dataclass
class MaintenanceEntry:
    date: str                  # ISO 8601, e.g. "2026-07-05"
    maintenance_type: str
    notes: str = ""


@dataclass
class AlertRule:
    metric: str
    comparison: str      # "lt" alerts when value < threshold, "gt" when value > threshold
    threshold: float
    label: str = ""      # shown in the alert message

    def __post_init__(self):
        if self.comparison not in VALID_COMPARISONS:
            raise ValueError(f"comparison must be one of {VALID_COMPARISONS}, got {self.comparison!r}")
        if not METRIC_NAME_RE.match(self.metric):
            raise ValueError(f"invalid metric name: {self.metric!r}")


@dataclass
class AirframeConfig:
    airframe_label: str
    checklist_items: list[str] = field(default_factory=list)
    maintenance_log: list[MaintenanceEntry] = field(default_factory=list)
    maintenance_interval_hours: Optional[float] = None
    alert_rules: list[AlertRule] = field(default_factory=list)
    webhook_url: Optional[str] = None
    token_hash: Optional[str] = None

    def to_dict(self) -> dict:
        # what clients see; token_hash stays out of it
        return {
            "airframe_label": self.airframe_label,
            "checklist_items": self.checklist_items,
            "maintenance_log": [asdict(m) for m in self.maintenance_log],
            "maintenance_interval_hours": self.maintenance_interval_hours,
            "alert_rules": [asdict(r) for r in self.alert_rules],
            "webhook_url": self.webhook_url,
        }

    def to_record(self) -> dict:
        return {**self.to_dict(), "token_hash": self.token_hash}

    @classmethod
    def from_dict(cls, data: dict) -> "AirframeConfig":
        return cls(
            airframe_label=data["airframe_label"],
            checklist_items=list(data.get("checklist_items", [])),
            maintenance_log=[MaintenanceEntry(**m) for m in data.get("maintenance_log", [])],
            maintenance_interval_hours=data.get("maintenance_interval_hours"),
            alert_rules=[AlertRule(**r) for r in data.get("alert_rules", [])],
            webhook_url=data.get("webhook_url"),
            token_hash=data.get("token_hash"),
        )


class TokenError(Exception):
    """reason is "unclaimed", "missing" or "invalid"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AirframeConfigStore:
    """One row per airframe in the `airframes` table: the config as JSON plus the token hash."""

    def _get(self, c, airframe_label: str) -> AirframeConfig:
        row = c.execute(
            "SELECT config_json, token_hash FROM airframes WHERE label = ?", (airframe_label,)
        ).fetchone()
        if row is None:
            return AirframeConfig(airframe_label=airframe_label)
        # a row that won't parse raises instead of coming back empty, so the
        # next save can't overwrite someone's real data
        data = json.loads(row["config_json"])
        data["airframe_label"] = airframe_label
        data["token_hash"] = row["token_hash"]
        return AirframeConfig.from_dict(data)

    def _save(self, c, config: AirframeConfig) -> None:
        now = time.time()
        c.execute(
            "INSERT INTO airframes (label, token_hash, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (label) DO UPDATE SET token_hash = excluded.token_hash,"
            " config_json = excluded.config_json, updated_at = excluded.updated_at",
            (config.airframe_label, config.token_hash, json.dumps(config.to_dict()), now, now),
        )

    def get(self, airframe_label: str) -> AirframeConfig:
        """Stored config, or an empty unclaimed one for a label nobody has used yet."""
        return self._get(db.get().conn(), airframe_label)

    def save(self, config: AirframeConfig) -> None:
        with db.get().transaction() as c:
            self._save(c, config)

    def authorise(self, airframe_label: str, token: Optional[str], claim: bool = False) -> Optional[str]:
        """Check `token` for this airframe, raising TokenError if it doesn't fit.

        With claim=True an unclaimed airframe is claimed instead, and the new
        token is returned; that's the only time it is ever available.
        """
        # a claim writes, so it takes the write lock before reading: two
        # first uploads racing can't both walk away with a token
        with db.get().transaction(immediate=claim) as c:
            config = self._get(c, airframe_label)
            if config.token_hash is None:
                if not claim:
                    raise TokenError("unclaimed")
                new_token = secrets.token_urlsafe(32)
                config.token_hash = hash_token(new_token)
                self._save(c, config)
                return new_token

            if not token:
                raise TokenError("missing")
            if not hmac.compare_digest(config.token_hash, hash_token(token)):
                raise TokenError("invalid")
            return None

    def add_maintenance_entry(self, airframe_label: str, entry: MaintenanceEntry) -> AirframeConfig:
        with db.get().transaction() as c:
            config = self._get(c, airframe_label)
            config.maintenance_log.append(entry)
            config.maintenance_log.sort(key=lambda m: m.date)
            self._save(c, config)
            return config

    def update_settings(
        self,
        airframe_label: str,
        checklist_items=_UNSET,
        maintenance_interval_hours=_UNSET,
        alert_rules=_UNSET,
        webhook_url=_UNSET,
    ) -> AirframeConfig:
        """Change only the fields passed. Passing None clears a field."""
        with db.get().transaction() as c:
            config = self._get(c, airframe_label)
            if checklist_items is not _UNSET:
                config.checklist_items = checklist_items or []
            if maintenance_interval_hours is not _UNSET:
                config.maintenance_interval_hours = maintenance_interval_hours
            if alert_rules is not _UNSET:
                config.alert_rules = alert_rules or []
            if webhook_url is not _UNSET:
                config.webhook_url = webhook_url or None
            self._save(c, config)
            return config


def compute_maintenance_status(config: AirframeConfig, flights_with_ts: list[tuple[float, object]]) -> dict:
    total_hours = sum(r.metadata.duration_seconds for _, r in flights_with_ts) / 3600.0

    last_maintenance_date = config.maintenance_log[-1].date if config.maintenance_log else None
    hours_since = total_hours
    if last_maintenance_date:
        try:
            cutoff = datetime.fromisoformat(last_maintenance_date).replace(tzinfo=timezone.utc).timestamp()
            hours_since = sum(
                r.metadata.duration_seconds for created_at, r in flights_with_ts if created_at >= cutoff
            ) / 3600.0
        except ValueError:
            pass

    maintenance_due = (
        config.maintenance_interval_hours is not None
        and hours_since >= config.maintenance_interval_hours
    )

    return {
        "total_flight_hours": total_hours,
        "hours_since_maintenance": hours_since,
        "maintenance_due": maintenance_due,
    }


def extract_metric_value(report, metric: str) -> Optional[float]:
    """Value of an alert-rule metric for this report, or None if the report doesn't have it.

    Rules can name metrics that an older or format-limited report never
    produced, so a miss is normal and never raises.
    """
    if metric == "overall_score":
        return report.overall_score

    if metric.startswith("module."):
        analyser_name = metric[len("module."):]
        for ar in report.analyser_results:
            if ar.analyser == analyser_name:
                return ar.health_score
        return None

    if "." in metric:
        analyser_name, key = metric.split(".", 1)
        for ar in report.analyser_results:
            if ar.analyser == analyser_name:
                return ar.key_metrics.get(key)
        return None

    return None


def evaluate_alert_rules(report, alert_rules: list[AlertRule]) -> list[dict]:
    """[{rule, value}] for every rule the report breaches. Missing metrics are skipped."""
    triggered = []
    for rule in alert_rules:
        value = extract_metric_value(report, rule.metric)
        if value is None:
            continue
        breached = (value < rule.threshold) if rule.comparison == "lt" else (value > rule.threshold)
        if breached:
            triggered.append({"rule": rule, "value": value})
    return triggered


airframe_store = AirframeConfigStore()
