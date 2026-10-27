from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

# anything before 2010 is a clock that was never set
MIN_EPOCH_US = 1_262_304_000_000_000


def utc_iso(epoch_us: float) -> str:
    return datetime.fromtimestamp(epoch_us / 1e6, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FlightMetadata(BaseModel):
    duration_seconds: float
    firmware_version: Optional[str] = None
    hardware_id: Optional[str] = None
    airframe_id: Optional[int] = None
    airframe_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    # ISO-8601 UTC of the first sample, e.g. "2026-10-01T09:12:33Z"; None when the log can't tell
    log_start_utc: Optional[str] = None
    arm_count: int = 0
    flight_modes_used: list[str] = []
    max_altitude_m: Optional[float] = None
    max_speed_ms: Optional[float] = None
    total_distance_m: Optional[float] = None
    px4_version: Optional[str] = None
    available_topics: list[str] = []
    weather: Optional[dict] = None
    location_name: Optional[str] = None
    gps_path: Optional[list[list[float]]] = None
    # same length and order as gps_path, None where a point has no reading;
    # the frontend colours the 3D path w/ these
    gps_path_wind_speed_ms: Optional[list[Optional[float]]] = None
    gps_path_hdop: Optional[list[Optional[float]]] = None
    # [start_s, end_s] pairs, log-relative seconds, from the arming state
    armed_windows: Optional[list[list[float]]] = None
    # things the parser had to skip or guess, in plain words for the report
    parse_warnings: list[str] = []
