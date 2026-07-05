"""
GET  /airframe/{label}/config       — config + computed maintenance status
PUT  /airframe/{label}/config       — update checklist/interval/alert rules/webhook
POST /airframe/{label}/maintenance  — append a maintenance log entry
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from api.airframe_store import (
    AirframeConfig, AlertRule, MaintenanceEntry, VALID_COMPARISONS,
    airframe_store, compute_maintenance_status,
)
from api.storage import job_store, normalise_airframe_label
from api.webhook_notifier import UnsafeWebhookURLError, validate_webhook_url

router = APIRouter()


class AlertRuleBody(BaseModel):
    metric: str
    comparison: str
    threshold: float
    label: str = ""

    @field_validator("comparison")
    @classmethod
    def _check_comparison(cls, v):
        if v not in VALID_COMPARISONS:
            raise ValueError(f"comparison must be one of {VALID_COMPARISONS}")
        return v


class AirframeConfigUpdate(BaseModel):
    checklist_items: Optional[list[str]] = None
    maintenance_interval_hours: Optional[float] = None
    alert_rules: Optional[list[AlertRuleBody]] = None
    webhook_url: Optional[str] = None


class MaintenanceEntryBody(BaseModel):
    date: str
    maintenance_type: str
    notes: str = ""


def _config_response(config: AirframeConfig, label: str) -> dict:
    flights = job_store.list_by_airframe_with_created_at(label)
    status = compute_maintenance_status(config, flights)

    return {
        **config.to_dict(),
        "total_flight_hours": round(status["total_flight_hours"], 2),
        "hours_since_maintenance": round(status["hours_since_maintenance"], 2),
        "maintenance_due": status["maintenance_due"],
        "flight_count": len(flights),
    }


@router.get("/airframe/{label}/config")
async def get_airframe_config(label: str) -> dict:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    config = airframe_store.get(normalised)
    return _config_response(config, normalised)


@router.put("/airframe/{label}/config")
async def update_airframe_config(label: str, body: AirframeConfigUpdate) -> dict:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")

    if body.webhook_url:
        try:
            validate_webhook_url(body.webhook_url)
        except UnsafeWebhookURLError as e:
            raise HTTPException(status_code=400, detail=str(e))

    alert_rules = None
    if body.alert_rules is not None:
        try:
            alert_rules = [
                AlertRule(metric=r.metric, comparison=r.comparison, threshold=r.threshold, label=r.label)
                for r in body.alert_rules
            ]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    config = airframe_store.update_settings(
        normalised,
        checklist_items=body.checklist_items,
        maintenance_interval_hours=body.maintenance_interval_hours,
        alert_rules=alert_rules,
        webhook_url=body.webhook_url,
    )
    return _config_response(config, normalised)


@router.post("/airframe/{label}/maintenance")
async def add_maintenance_entry(label: str, body: MaintenanceEntryBody) -> dict:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    try:
        datetime.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be an ISO 8601 date, e.g. 2026-07-05")

    config = airframe_store.add_maintenance_entry(
        normalised,
        MaintenanceEntry(date=body.date, maintenance_type=body.maintenance_type, notes=body.notes),
    )
    return _config_response(config, normalised)
