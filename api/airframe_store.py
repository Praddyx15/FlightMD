"""
Per-airframe settings that outlive any single flight: maintenance log,
pre-flight checklist, alert rules and webhook.

There's no "register an airframe" step. A label exists once someone tags a
flight with it or writes its config, and the first of those claims it: the
caller gets a random airframe token back once, and every later read or write
has to present it. Only a sha256 of the token is stored.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from api.fs import write_json_atomic

logger = logging.getLogger(__name__)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "airframes"))

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


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip())
    return slug[:60] or "unnamed"


def _filename(label: str) -> str:
    # The slug alone collides ("Quad 1", "Quad_1", "Quad#1"); the hash keeps
    # every exact label in its own file, the slug just keeps the dir readable.
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    return f"{_slugify(label)[:40]}-{digest}.json"


class AirframeConfigStore:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        os.makedirs(self.data_dir, exist_ok=True)

    def _path(self, airframe_label: str) -> str:
        return os.path.join(self.data_dir, _filename(airframe_label))

    def _legacy_path(self, airframe_label: str) -> str:
        return os.path.join(self.data_dir, f"{_slugify(airframe_label)}.json")

    def _read(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get(self, airframe_label: str) -> AirframeConfig:
        """Stored config, or an empty unclaimed one for a label nobody has used yet.

        A file that exists but won't parse raises instead of coming back
        empty, so the next save can't overwrite someone's real data.
        """
        with self._lock:
            path = self._path(airframe_label)
            if os.path.exists(path):
                return AirframeConfig.from_dict(self._read(path))

            # pre-hash files were named by slug only; use one if the label matches exactly
            legacy = self._legacy_path(airframe_label)
            if os.path.exists(legacy):
                data = self._read(legacy)
                if data.get("airframe_label") == airframe_label:
                    return AirframeConfig.from_dict(data)

            return AirframeConfig(airframe_label=airframe_label)

    def save(self, config: AirframeConfig) -> None:
        with self._lock:
            write_json_atomic(self._path(config.airframe_label), config.to_record(), indent=2)
            legacy = self._legacy_path(config.airframe_label)
            if os.path.exists(legacy):
                try:
                    if self._read(legacy).get("airframe_label") == config.airframe_label:
                        os.remove(legacy)
                except (OSError, ValueError) as e:
                    logger.warning(f"left legacy airframe file {legacy} in place: {e}")

    def authorise(self, airframe_label: str, token: Optional[str], claim: bool = False) -> Optional[str]:
        """Check `token` for this airframe, raising TokenError if it doesn't fit.

        With claim=True an unclaimed airframe is claimed instead, and the new
        token is returned; that's the only time it is ever available.
        """
        with self._lock:
            config = self.get(airframe_label)
            if config.token_hash is None:
                if not claim:
                    raise TokenError("unclaimed")
                new_token = secrets.token_urlsafe(32)
                config.token_hash = hash_token(new_token)
                self.save(config)
                return new_token

            if not token:
                raise TokenError("missing")
            if not hmac.compare_digest(config.token_hash, hash_token(token)):
                raise TokenError("invalid")
            return None

    def add_maintenance_entry(self, airframe_label: str, entry: MaintenanceEntry) -> AirframeConfig:
        with self._lock:
            config = self.get(airframe_label)
            config.maintenance_log.append(entry)
            config.maintenance_log.sort(key=lambda m: m.date)
            self.save(config)
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
        with self._lock:
            config = self.get(airframe_label)
            if checklist_items is not _UNSET:
                config.checklist_items = checklist_items or []
            if maintenance_interval_hours is not _UNSET:
                config.maintenance_interval_hours = maintenance_interval_hours
            if alert_rules is not _UNSET:
                config.alert_rules = alert_rules or []
            if webhook_url is not _UNSET:
                config.webhook_url = webhook_url or None
            self.save(config)
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
