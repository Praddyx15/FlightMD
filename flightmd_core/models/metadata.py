"""
FlightMetadata — extracted from ULog message headers and params.
"""

from pydantic import BaseModel
from typing import Optional


class FlightMetadata(BaseModel):
    duration_seconds: float
    firmware_version: Optional[str] = None
    hardware_id: Optional[str] = None
    airframe_id: Optional[int] = None
    airframe_name: Optional[str] = None
    vehicle_type: Optional[str] = None
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
    # Parallel arrays, same length/order as gps_path — one entry per path
    # point, None where that point has no reading. Lets the frontend color
    # the 3D flight path by wind speed or GPS signal quality instead of a
    # flat colour.
    gps_path_wind_speed_ms: Optional[list[Optional[float]]] = None
    gps_path_hdop: Optional[list[Optional[float]]] = None
