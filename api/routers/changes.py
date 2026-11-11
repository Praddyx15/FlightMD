"""
Tune, fly, verify: record a parameter change applied after a flight, then see
whether the airframe's next flight shows it working. Both routes need the
airframe's X-Airframe-Token.
"""

import re
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.param_changes import param_change_store, pending, with_verification
from api.security import check_airframe_token
from api.storage import JobStatus, job_store, normalise_airframe_label

router = APIRouter(tags=["Airframe"])

AUTH_RESPONSES = {
    401: {"description": "Token missing, or airframe not claimed yet"},
    403: {"description": "Wrong token"},
}

# PX4 and ArduPilot names are at most 16 chars; a bit of slack for other stacks
_PARAM_NAME = re.compile(r"^[A-Za-z0-9_]{1,32}$")


class ParamChange(BaseModel):
    name: str
    from_value: Optional[float] = None
    to_value: float

    @field_validator("name")
    @classmethod
    def _check_name(cls, v):
        if not _PARAM_NAME.match(v):
            raise ValueError("parameter names are letters, digits and _ (32 at most)")
        return v


class ChangeBody(BaseModel):
    report_id: str = Field(min_length=1, max_length=64)
    changes: list[ParamChange] = Field(min_length=1, max_length=50)
    applied_by: Literal["user", "uaop"] = "user"
    note: Optional[str] = Field(None, max_length=500)


def _label_or_400(label: str) -> str:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    return normalised


@router.post("/airframe/{label}/changes", status_code=201, summary="Record applied parameter changes",
             responses={**AUTH_RESPONSES, 400: {"description": "report_id isn't a finished flight of this airframe"}})
def add_change(label: str, body: ChangeBody, x_airframe_token: Optional[str] = Header(None)) -> dict:
    normalised = _label_or_400(label)
    check_airframe_token(normalised, x_airframe_token)

    job = job_store.get(body.report_id)
    if job is None or job.status != JobStatus.COMPLETE or job.airframe_label != normalised:
        raise HTTPException(status_code=400, detail="report_id must be a finished flight tagged with this airframe.")

    row = param_change_store.add(
        normalised, body.report_id,
        [c.model_dump() for c in body.changes],
        body.applied_by, body.note,
    )
    # recorded just now, so there's no later flight yet
    return {**row, "verify": pending()}


@router.get("/airframe/{label}/changes", summary="Applied parameter changes and whether they worked",
            responses=AUTH_RESPONSES)
def list_changes(label: str, x_airframe_token: Optional[str] = Header(None)) -> list[dict]:
    """Newest first. `verify.status` is pending until a later tagged flight exists, then
    improved, unchanged, worse or mixed."""
    normalised = _label_or_400(label)
    check_airframe_token(normalised, x_airframe_token)
    return with_verification(normalised, param_change_store.for_airframe(normalised))
