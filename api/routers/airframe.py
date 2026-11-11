"""
Airframe config and maintenance log.

Every route here needs the airframe's X-Airframe-Token. The first write to an
unclaimed airframe claims it instead, and that response carries
`airframe_token`, the only time the token is ever shown.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from api import airframe_store as afs
from api.security import check_airframe_token, precheck_airframe_token
from api.storage import job_store, normalise_airframe_label
from api.webhook_notifier import UnsafeWebhookURLError, validate_webhook_url

router = APIRouter(tags=["Airframe"])

AUTH_RESPONSES = {
    401: {"description": "Token missing, or airframe not claimed yet"},
    403: {"description": "Wrong token"},
}


class AlertRuleBody(BaseModel):
    metric: str
    comparison: str
    threshold: float
    label: str = Field("", max_length=120)

    @field_validator("comparison")
    @classmethod
    def _check_comparison(cls, v):
        if v not in afs.VALID_COMPARISONS:
            raise ValueError(f"comparison must be one of {afs.VALID_COMPARISONS}")
        return v


class AirframeConfigUpdate(BaseModel):
    # Fields left out stay as they are; an explicit null clears the field.
    checklist_items: Optional[list[str]] = Field(None, max_length=50)
    maintenance_interval_hours: Optional[float] = Field(None, gt=0, le=100_000)
    alert_rules: Optional[list[AlertRuleBody]] = Field(None, max_length=20)
    webhook_url: Optional[str] = None

    @field_validator("checklist_items")
    @classmethod
    def _check_items(cls, v):
        if v and any(len(item) > 200 for item in v):
            raise ValueError("checklist items are limited to 200 characters")
        return v


class MaintenanceEntryBody(BaseModel):
    date: str
    maintenance_type: str = Field(min_length=1, max_length=120)
    notes: str = Field("", max_length=2000)


def _label_or_400(label: str) -> str:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    return normalised


def _config_response(config: afs.AirframeConfig, label: str, new_token: Optional[str] = None) -> dict:
    flights = job_store.list_by_airframe_with_created_at(label)
    status = afs.compute_maintenance_status(config, flights)
    out = {
        **config.to_dict(),
        "total_flight_hours": round(status["total_flight_hours"], 2),
        "hours_since_maintenance": round(status["hours_since_maintenance"], 2),
        "maintenance_due": status["maintenance_due"],
        "flight_count": len(flights),
    }
    if new_token:
        out["airframe_token"] = new_token
    return out


# sync defs: these touch the disk, so FastAPI runs them in its threadpool

@router.get("/airframe/{label}/config", summary="Airframe config and maintenance status", responses=AUTH_RESPONSES)
def get_airframe_config(label: str, x_airframe_token: Optional[str] = Header(None)) -> dict:
    normalised = _label_or_400(label)
    check_airframe_token(normalised, x_airframe_token)
    return _config_response(afs.airframe_store.get(normalised), normalised)


@router.put("/airframe/{label}/config", summary="Update checklist, interval, alert rules or webhook",
            responses=AUTH_RESPONSES)
def update_airframe_config(
    label: str,
    body: AirframeConfigUpdate,
    x_airframe_token: Optional[str] = Header(None),
) -> dict:
    normalised = _label_or_400(label)
    needs_claim = precheck_airframe_token(normalised, x_airframe_token)

    if body.webhook_url:
        try:
            validate_webhook_url(body.webhook_url)
        except UnsafeWebhookURLError as e:
            raise HTTPException(status_code=400, detail=str(e))

    changes = {name: getattr(body, name) for name in body.model_fields_set}
    if body.alert_rules is not None:
        try:
            changes["alert_rules"] = [
                afs.AlertRule(metric=r.metric, comparison=r.comparison, threshold=r.threshold, label=r.label)
                for r in body.alert_rules
            ]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    new_token = check_airframe_token(normalised, x_airframe_token, claim=True) if needs_claim else None
    config = afs.airframe_store.update_settings(normalised, **changes)
    return _config_response(config, normalised, new_token)


@router.post("/airframe/{label}/maintenance", summary="Log a maintenance entry", responses=AUTH_RESPONSES)
def add_maintenance_entry(
    label: str,
    body: MaintenanceEntryBody,
    x_airframe_token: Optional[str] = Header(None),
) -> dict:
    normalised = _label_or_400(label)
    needs_claim = precheck_airframe_token(normalised, x_airframe_token)
    try:
        datetime.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be an ISO 8601 date, e.g. 2026-07-05")

    new_token = check_airframe_token(normalised, x_airframe_token, claim=True) if needs_claim else None
    config = afs.airframe_store.add_maintenance_entry(
        normalised,
        afs.MaintenanceEntry(date=body.date, maintenance_type=body.maintenance_type, notes=body.notes),
    )
    return _config_response(config, normalised, new_token)
