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
