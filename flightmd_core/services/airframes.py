"""
Airframe names from the parameters.

PX4: SYS_AUTOSTART looked up in data/px4_airframes.json, trimmed from PX4's
airframes.xml plus the airframe reference of v1.12-v1.15 so ids removed in later
releases still resolve. ArduPilot: FRAME_CLASS / FRAME_TYPE (Q_ for quadplanes,
FRAME_CONFIG for Sub), values from apm.pdef.xml.
"""

import json
from functools import lru_cache
from importlib import resources
from typing import Optional

COPTER_CLASS = {
    1: "Quad", 2: "Hexa", 3: "Octa", 4: "OctaQuad", 5: "Y6", 6: "Heli", 7: "Tri",
    8: "SingleCopter", 9: "CoaxCopter", 10: "BiCopter", 11: "Heli_Dual", 12: "DodecaHexa",
    13: "HeliQuad", 14: "Deca", 15: "Scripting Matrix", 16: "6DoF Scripting",
    17: "Dynamic Scripting Matrix",
}
COPTER_TYPE = {
    0: "Plus", 1: "X", 2: "V", 3: "H", 4: "V-Tail", 5: "A-Tail", 10: "Y6B", 11: "Y6F",
    12: "BetaFlightX", 13: "DJIX", 14: "ClockwiseX", 15: "I", 16: "NYT Plus", 17: "NYT X",
    18: "BetaFlightXReversed", 19: "Y4",
}
# classes where FRAME_TYPE is ignored by the firmware
_TYPELESS = {6, 8, 9, 10, 11, 13, 15, 16, 17}
QUADPLANE_CLASS = {**COPTER_CLASS, 10: "Single/Dual"}
ROVER_CLASS = {1: "Rover", 2: "Boat", 3: "BalanceBot"}
ROVER_TYPE = {1: "Omni3", 2: "OmniX", 3: "OmniPlus", 4: "Omni3Mecanum"}
SUB_CONFIG = {
    0: "BlueROV1", 1: "Vectored", 2: "Vectored_6DOF", 3: "Vectored_6DOF_90",
    4: "SimpleROV-3", 5: "SimpleROV-4", 6: "SimpleROV-5", 7: "Custom",
}


@lru_cache(maxsize=1)
def _px4_table() -> dict:
    with resources.files("flightmd_core").joinpath("data/px4_airframes.json").open(encoding="utf-8") as f:
        return json.load(f)


def px4_airframe(autostart) -> tuple[Optional[str], Optional[str]]:
    """(name, frame type) for a SYS_AUTOSTART id, or (None, None)."""
    if autostart is None:
        return None, None
    try:
        key = str(int(autostart))
    except (TypeError, ValueError):
        return None, None
    hit = _px4_table().get(key)
    if hit is None:
        return None, None
    return hit["name"], hit.get("type")


def _int(params: dict, name: str) -> Optional[int]:
    v = params.get(name)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _multirotor(cls_map, cls: Optional[int], typ: Optional[int]) -> Optional[str]:
    name = cls_map.get(cls)
    if name is None:
        return None
    if cls in _TYPELESS or typ not in COPTER_TYPE:
        return name
    return f"{name} {COPTER_TYPE[typ]}"


def ardupilot_frame(params: dict, vehicle_type: Optional[str]) -> Optional[str]:
    """Frame name like "Quad X" or "QuadPlane Hexa Plus". vehicle_type is the
    parser's "Copter" / "Plane" / "Rover" / "Sub": FRAME_CLASS means different
    things on Copter and Rover."""
    if vehicle_type is None and ("ATC_STR_RAT_P" in params or "CRUISE_SPEED" in params):
        vehicle_type = "Rover"
    if vehicle_type == "VTOL":
        vehicle_type = "Plane"
    # todo: Blimp and AntennaTracker frames aren't mapped yet
    if vehicle_type == "Sub":
        return SUB_CONFIG.get(_int(params, "FRAME_CONFIG"))
    if vehicle_type == "Rover":
        name = ROVER_CLASS.get(_int(params, "FRAME_CLASS"))
        typ = ROVER_TYPE.get(_int(params, "FRAME_TYPE"))
        return f"{name} {typ}" if name and typ else name
    if vehicle_type == "Plane" or "Q_ENABLE" in params:
        if (_int(params, "Q_ENABLE") or 0) >= 1:
            frame = _multirotor(QUADPLANE_CLASS, _int(params, "Q_FRAME_CLASS"), _int(params, "Q_FRAME_TYPE"))
            return f"QuadPlane {frame}" if frame else "QuadPlane"
        return "Plane" if vehicle_type == "Plane" else None
    return _multirotor(COPTER_CLASS, _int(params, "FRAME_CLASS"), _int(params, "FRAME_TYPE"))
