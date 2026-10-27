"""
Prometheus metrics at GET /metrics.

HTTP metrics come from prometheus-fastapi-instrumentator (route templates
only, never raw paths). On top of that, analyses by format and outcome and
how long they took. Labels are bounded sets: no ids, filenames or positions.
With the Redis queue the analysis counters live in the worker process, not here.
"""

import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from api.config import get_settings

KNOWN_FORMATS = {
    "px4_ulog", "ardupilot_bin", "ardupilot_log", "mavlink_tlog",
    "betaflight_bbl", "dji_txt", "dji_dat", "compressed",
}
OUTCOMES = {"complete", "rejected", "error", "deduplicated"}

ANALYSES = Counter(
    "flightmd_analyses_total",
    "Analyses by log format and outcome",
    ["format", "outcome"],
)
DURATION = Histogram(
    "flightmd_analysis_duration_seconds",
    "Time spent analysing one log, queue wait not included",
    ["format"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)

router = APIRouter()


def _fmt(log_format: Optional[str]) -> str:
    return log_format if log_format in KNOWN_FORMATS else "other"


def count_analysis(log_format: Optional[str], outcome: str) -> None:
    ANALYSES.labels(format=_fmt(log_format), outcome=outcome if outcome in OUTCOMES else "error").inc()


def observe_duration(log_format: Optional[str], seconds: float) -> None:
    DURATION.labels(format=_fmt(log_format)).observe(seconds)


def instrument(app) -> None:
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics"],
    ).instrument(app)


def _check_token(authorization: Optional[str]) -> None:
    expected = get_settings().metrics_token
    if not expected:
        return
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not given:
        raise HTTPException(status_code=401, detail="Metrics need a bearer token.",
                            headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Wrong metrics token.")


@router.get("/metrics", include_in_schema=False)
def metrics(authorization: Optional[str] = Header(None)) -> Response:
    _check_token(authorization)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
