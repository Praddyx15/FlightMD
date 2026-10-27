"""
Autopilot and frame type from the parameter set, so advice names parameters
the vehicle actually uses (MC_* on a PX4 plane would retune its VTOL
hover gains, not the wing).

autopilot: "px4" | "ardupilot" | "unknown"
frame:     "multirotor" | "fixed_wing" | "vtol" | "rover" | "unknown"
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Vehicle:
    autopilot: str
    frame: str


# PX4 MAV_TYPE (MAVLink MAV_TYPE enum)
_PX4_MAV_TYPE = {
    1: "fixed_wing",
    2: "multirotor", 3: "multirotor", 4: "multirotor", 13: "multirotor",
    14: "multirotor", 15: "multirotor", 29: "multirotor",
    10: "rover", 11: "rover",
    19: "vtol", 20: "vtol", 21: "vtol", 22: "vtol", 23: "vtol",
}

_ARDU_MARKERS = ("ATC_", "INS_", "AHRS_", "SYSID_", "SERVO1_", "ARMING_CHECK",
                 "BATT_MONITOR", "RLL2SRV_", "Q_ENABLE", "FRAME_CLASS")
_PX4_MARKERS = ("MAV_TYPE", "SYS_AUTOSTART", "EKF2_", "MPC_", "MC_", "COM_", "NAV_DLL_")


def _px4_frame(params: dict) -> str:
    mav_type = params.get("MAV_TYPE")
    if mav_type is not None and int(mav_type) in _PX4_MAV_TYPE:
        return _PX4_MAV_TYPE[int(mav_type)]

    # airframe id ranges from PX4's ROMFS init.d/airframes
    autostart = int(params.get("SYS_AUTOSTART", 0) or 0)
    if 13000 <= autostart < 14000:
        return "vtol"
    if 2000 <= autostart < 4000:
        return "fixed_wing"
    if 4000 <= autostart < 17000:
        return "multirotor"
    if 50000 <= autostart < 61000:
        return "rover"

    # every PX4 build carries both MC_* and FW_* params, so this last guess
    # only works on trimmed sets (tests, hand-made files)
    if "VT_TYPE" in params:
        return "vtol"
    if "MC_ROLLRATE_P" in params and "FW_RR_P" not in params:
        return "multirotor"
    if "FW_RR_P" in params and "MC_ROLLRATE_P" not in params:
        return "fixed_wing"
    return "unknown"


def _ardupilot_frame(params: dict) -> str:
    if "ATC_STR_RAT_P" in params or "CRUISE_THROTTLE" in params:
        return "rover"
    if params.get("Q_ENABLE", 0) >= 1:
        return "vtol"
    if "FRAME_CLASS" in params or "ATC_RAT_RLL_P" in params:
        return "multirotor"
    if any(k in params for k in ("RLL_RATE_P", "RLL2SRV_P", "PTCH2SRV_P", "TECS_CLMB_MAX")):
        return "fixed_wing"
    return "unknown"


def vehicle_from_params(params: dict) -> Vehicle:
    keys = list(params)
    if any(k.startswith(_ARDU_MARKERS) for k in keys):
        return Vehicle("ardupilot", _ardupilot_frame(params))
    if any(k.startswith(_PX4_MARKERS) for k in keys):
        return Vehicle("px4", _px4_frame(params))
    return Vehicle("unknown", "unknown")


# Roll/pitch/yaw rate-loop P and D names per (autopilot, frame).
# None = no such gain or no safe single-parameter advice.
RATE_GAINS = {
    ("px4", "multirotor"): {
        "roll":  ("MC_ROLLRATE_P", "MC_ROLLRATE_D"),
        "pitch": ("MC_PITCHRATE_P", "MC_PITCHRATE_D"),
        "yaw":   ("MC_YAWRATE_P", "MC_YAWRATE_D"),
    },
    ("px4", "fixed_wing"): {
        "roll":  ("FW_RR_P", None),
        "pitch": ("FW_PR_P", None),
        "yaw":   ("FW_YR_P", None),
    },
    ("ardupilot", "multirotor"): {
        "roll":  ("ATC_RAT_RLL_P", "ATC_RAT_RLL_D"),
        "pitch": ("ATC_RAT_PIT_P", "ATC_RAT_PIT_D"),
        "yaw":   ("ATC_RAT_YAW_P", "ATC_RAT_YAW_D"),
    },
    ("ardupilot", "fixed_wing"): {
        "roll":  ("RLL_RATE_P", "RLL_RATE_D"),
        "pitch": ("PTCH_RATE_P", "PTCH_RATE_D"),
        "yaw":   (None, None),
    },
}


def rate_gain_names(vehicle: Vehicle, axis: str) -> tuple:
    """(P name, D name) for this vehicle and axis; (None, None) when there's
    no gain we'd recommend touching (VTOL, rover, unknown)."""
    return RATE_GAINS.get((vehicle.autopilot, vehicle.frame), {}).get(axis, (None, None))
