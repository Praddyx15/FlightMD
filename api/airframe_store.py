"""
AirframeConfigStore — per-airframe configuration: maintenance log, pre-flight
checklist, and alert rules/webhook for cross-flight monitoring.

This is deliberately separate from JobStore (api/storage.py): a Job is a
single flight's analysis result; an AirframeConfig is metadata about the
*airframe itself* that persists across many flights. Airframes only exist
here once someone tags a flight with that label — there's no separate
"register an airframe" step.
"""

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "airframes"))

VALID_COMPARISONS = ("lt", "gt")

# key_metrics are namespaced "{analyser}.{metric}" (e.g. "battery.sag_per_cell_v");
# "overall_score" and "module.<name>" (e.g. "module.battery") are also valid.
METRIC_NAME_RE = re.compile(r"^[a-zA-Z0-9_.]{1,64}$")


@dataclass
class MaintenanceEntry:
    date: str                  # ISO 8601 date, e.g. "2026-07-05"
    maintenance_type: str      # e.g. "Propeller replacement", "Full inspection"
    notes: str = ""


@dataclass
class AlertRule:
    metric: str          # "overall_score" | "module.<analyser>" | "<analyser>.<key_metric>"
    comparison: str      # "lt" (alert if value < threshold) | "gt" (alert if value > threshold)
    threshold: float
    label: str = ""      # human-readable description shown in the alert message

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

    def to_dict(self) -> dict:
        return {
            "airframe_label": self.airframe_label,
            "checklist_items": self.checklist_items,
            "maintenance_log": [asdict(m) for m in self.maintenance_log],
            "maintenance_interval_hours": self.maintenance_interval_hours,
            "alert_rules": [asdict(r) for r in self.alert_rules],
            "webhook_url": self.webhook_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AirframeConfig":
        return cls(
            airframe_label=data["airframe_label"],
            checklist_items=list(data.get("checklist_items", [])),
            maintenance_log=[MaintenanceEntry(**m) for m in data.get("maintenance_log", [])],
            maintenance_interval_hours=data.get("maintenance_interval_hours"),
            alert_rules=[AlertRule(**r) for r in data.get("alert_rules", [])],
            webhook_url=data.get("webhook_url"),
        )


def _slugify(label: str) -> str:
    """Filesystem-safe slug for the config filename. The original label
    (with its real casing/spacing) is preserved inside the stored JSON —
    this only affects the on-disk filename."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip())
    return slug[:60] or "unnamed"


class AirframeConfigStore:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self._lock = threading.Lock()
        os.makedirs(self.data_dir, exist_ok=True)

    def _path(self, airframe_label: str) -> str:
        return os.path.join(self.data_dir, f"{_slugify(airframe_label)}.json")

    def get(self, airframe_label: str) -> AirframeConfig:
        """Returns a default (empty) config if none exists yet — airframes
        aren't explicitly created, they come into being the first time
        someone configures or tags one."""
        path = self._path(airframe_label)
        with self._lock:
            if not os.path.exists(path):
                return AirframeConfig(airframe_label=airframe_label)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return AirframeConfig.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to load airframe config for {airframe_label!r}: {e}")
                return AirframeConfig(airframe_label=airframe_label)

    def save(self, config: AirframeConfig) -> None:
        path = self._path(config.airframe_label)
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2)

    def add_maintenance_entry(self, airframe_label: str, entry: MaintenanceEntry) -> AirframeConfig:
        config = self.get(airframe_label)
        config.maintenance_log.append(entry)
        config.maintenance_log.sort(key=lambda m: m.date)
        self.save(config)
        return config

    def update_settings(
        self,
        airframe_label: str,
        checklist_items: Optional[list[str]] = None,
        maintenance_interval_hours: Optional[float] = None,
        alert_rules: Optional[list[AlertRule]] = None,
        webhook_url: Optional[str] = None,
    ) -> AirframeConfig:
        config = self.get(airframe_label)
        if checklist_items is not None:
            config.checklist_items = checklist_items
        if maintenance_interval_hours is not None:
            config.maintenance_interval_hours = maintenance_interval_hours
        if alert_rules is not None:
            config.alert_rules = alert_rules
        if webhook_url is not None:
            config.webhook_url = webhook_url or None
        self.save(config)
        return config


def compute_maintenance_status(config: AirframeConfig, flights_with_ts: list[tuple[float, object]]) -> dict:
    """
    Shared by the airframe config endpoint and the PDF export — both need
    the same total-hours / hours-since-last-maintenance / due-flag
    computation from an airframe's flight history.
    """
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
    """
    Resolve an alert-rule metric name against a FlightMDReport:
      - "overall_score"        -> report.overall_score
      - "module.<analyser>"    -> that analyser's health_score
      - "<analyser>.<key>"     -> that analyser's key_metrics[key]
    Returns None if the metric doesn't apply to this report (e.g. a
    module that was skipped, or a key_metric that format didn't produce)
    — never raises, since alert rules may reference metrics an older or
    format-limited report doesn't have.
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
    """Returns a list of {rule, value} dicts for every rule the report's
    metrics actually breach. A rule referencing a metric this report
    doesn't have is silently skipped, not treated as a breach."""
    triggered = []
    for rule in alert_rules:
        value = extract_metric_value(report, rule.metric)
        if value is None:
            continue
        breached = (value < rule.threshold) if rule.comparison == "lt" else (value > rule.threshold)
        if breached:
            triggered.append({"rule": rule, "value": value})
    return triggered


# Global singleton — imported by routers
airframe_store = AirframeConfigStore()
