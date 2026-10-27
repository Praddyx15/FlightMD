"""
ArduPilot dataflash (.bin) parser on top of pymavlink's DFReader. Maps the messages the
analysers use onto the PX4 topic and column names (see ulog_parser.py), so every
analyser runs on ArduPilot logs unchanged.

Time is each message's TimeUS (boot clock) shifted so the log starts at 0. DFReader's
own _timestamp jumps to GPS/epoch time once the GPS gets a fix, so it isn't used.

estimator_status is deliberately not produced. XKF/NKF messages use other field names
and other bit meanings than PX4's innovation_check_flags / solution_status_flags, and a
guessed bitmask would give EKF findings that look exact but aren't. The EKF analyser
skips when the topic is missing.
"""

import logging
import os
import re
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import FlightMetadata, utc_iso

logger = logging.getLogger(__name__)

# pre-4.0 logs use numbered message names instead of an instance feild
WANTED_TYPES = {
    "IMU", "IMU2", "IMU3", "BAT", "BAT2", "GPS", "GPS2", "MODE", "MSG", "EV", "ARM",
    "ESC", *(f"ESC{i}" for i in range(1, 9)),
}

# LogEvent ids from ArduPilot's AP_Logger
EV_ARMED, EV_DISARMED, EV_LAND_COMPLETE, EV_NOT_LANDED = 10, 11, 18, 28

GPS_EPOCH_UNIX_S = 315_964_800  # 1980-01-06
GPS_LEAP_S = 18                 # GPS - UTC since 2017

_FIRMWARE_TO_VEHICLE_TYPE = {
    "ArduCopter": "Copter",
    "ArduPlane": "Plane",
    "ArduRover": "Rover",
    "ArduSub": "Sub",
    "Blimp": "Blimp",
    "AntennaTracker": "AntennaTracker",
    "APM:Copter": "Copter",
    "APM:Plane": "Plane",
    "APM:Rover": "Rover",
}

# ArduPilot mode name -> nearest PX4 nav_state. Rough by nature: modes that have no
# PX4 counterpart (DRIFT, SPORT, AUTOTUNE, THROW...) are left out and come back as NaN.
_MODE_TO_NAV_STATE = {
    "MANUAL": 0, "ALT_HOLD": 1, "QHOVER": 1, "FBWB": 1,
    "POSHOLD": 2, "QLOITER": 2, "CRUISE": 2,
    "AUTO": 3, "BRAKE": 4, "HOLD": 4,
    "RTL": 5, "SMART_RTL": 5, "AUTO_RTL": 5, "QRTL": 5,
    "ACRO": 10, "QACRO": 10, "GUIDED": 14,
    "STABILIZE": 15, "QSTABILIZE": 15, "FBWA": 15,
    "TAKEOFF": 17, "LAND": 18, "QLAND": 18, "FOLLOW": 19,
}


def ardupilot_nav_state(mode: Optional[str], vehicle: Optional[str]) -> float:
    if not mode:
        return np.nan
    mode = mode.upper()
    # copter LOITER is pilot-flown position hold; plane/rover LOITER is an auto hold
    if mode == "LOITER":
        return 2 if vehicle == "Copter" else 4
    if mode == "CIRCLE":
        return 21 if vehicle == "Copter" else 4
    return _MODE_TO_NAV_STATE.get(mode, np.nan)


def _instance(d: dict, field: str, mtype: str) -> int:
    if d.get(field) is not None:
        return int(d[field])
    m = re.search(r"(\d)$", mtype)
    return int(m.group(1)) - 1 if m else 0


def _boot_us(d: dict) -> Optional[int]:
    if d.get("TimeUS") is not None:
        return int(d["TimeUS"])
    if d.get("TimeMS") is not None:
        return int(d["TimeMS"]) * 1000
    return None


def _frame(rows, cols) -> pd.DataFrame:
    # a field missing from every message comes through as an all-None object column
    return pd.DataFrame(rows, columns=cols).astype({c: "float64" for c in cols[1:]})


def store_instances(topics, name, frames: dict[int, pd.DataFrame]) -> None:
    """Lowest instance under the bare name, the others as name_<instance>."""
    for k, i in enumerate(sorted(frames)):
        df = frames[i].reset_index(drop=True)
        topics[name if k == 0 else f"{name}_{i}"] = df


def merge_esc(frames: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """
    ESC instances are logged one message each, at slightly different times, so an exact
    timestamp join leaves every row mostly empty. Bin all of them onto one time base
    (bin = slowest instance's median interval), average inside a bin, and start where
    every ESC has reported. Gaps stay NaN.
    """
    dts = [np.median(np.diff(f["timestamp"].to_numpy())) for f in frames.values() if len(f) > 1]
    width = max(int(max(dts)) if dts else 100_000, 1_000)
    t0 = min(int(f["timestamp"].min()) for f in frames.values())

    out = None
    for i in sorted(frames):
        f = frames[i]
        b = (f["timestamp"].to_numpy() - t0) // width
        g = f.drop(columns="timestamp").groupby(b).mean()
        g.columns = [f"esc[{i}].{c}" for c in g.columns]
        out = g if out is None else out.join(g, how="outer")
    out = out.sort_index()

    first = max(
        out[[c for c in out.columns if c.startswith(f"esc[{i}].")]].notna().any(axis=1).idxmax()
        for i in frames
    )
    out = out.loc[first:]
    out.insert(0, "timestamp", t0 + out.index.to_numpy() * width)
    out["esc_count"] = len(frames)
    return out.reset_index(drop=True)


class ArduPilotBinParser:
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    def parse(
        self,
        bin_path: str,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(bin_path):
            raise FileNotFoundError(f"ArduPilot log file not found: {bin_path}")

        from pymavlink import DFReader

        logger.info(f"Parsing ArduPilot dataflash log: {bin_path}")
        reader = DFReader.DFReader_binary(bin_path)

        imu = defaultdict(list)
        bat = defaultdict(list)
        gps = defaultdict(list)
        esc = defaultdict(list)
        arm_msgs, arm_evs, land, modes = [], [], [], []
        firmware_version = None
        gps_utc = None  # (boot_us, utc_us) of the first 3D fix with GPS time
        first_us = last_us = None

        while True:
            msg = reader.recv_match(type=WANTED_TYPES)
            if msg is None:
                break
            mtype = msg.get_type()
            d = msg.to_dict()
            ts = _boot_us(d)
            if ts is None:
                # very old logs: MSG and friends carry no time at all
                ts = last_us or 0
            else:
                first_us = ts if first_us is None else min(first_us, ts)
                last_us = ts if last_us is None else max(last_us, ts)

            if mtype.startswith("IMU"):
                imu[_instance(d, "I", mtype)].append((
                    ts, d.get("GyrX"), d.get("GyrY"), d.get("GyrZ"),
                    d.get("AccX"), d.get("AccY"), d.get("AccZ"),
                ))

            elif mtype.startswith("BAT"):
                # todo: BAT.Res is ArduPilot's own internal resistance estimate, worth passing on
                bat[_instance(d, "Inst", mtype)].append((
                    ts, d.get("Volt"), d.get("Curr"), d.get("Temp"),
                    d.get("CurrTot"), d.get("RemPct"),
                ))

            elif mtype.startswith("GPS"):
                status = d.get("Status")
                gps[_instance(d, "I", mtype)].append((
                    ts, d.get("Lat"), d.get("Lng", d.get("Lon")), d.get("Alt"),
                    d.get("NSats"), d.get("HDop"), status,
                ))
                if gps_utc is None and status is not None and status >= 3 and d.get("GWk"):
                    utc = (GPS_EPOCH_UNIX_S + d["GWk"] * 604_800 - GPS_LEAP_S) * 1_000_000 + d.get("GMS", 0) * 1000
                    gps_utc = (ts, utc)

            elif mtype.startswith("ESC"):
                esc[_instance(d, "Instance", mtype)].append((
                    ts, d.get("RPM"), d.get("Volt"), d.get("Curr"), d.get("Temp"),
                ))

            elif mtype == "MODE":
                # DFReader turns the mode number into a name once it knows the vehicle
                name = getattr(reader, "flightmode", None)
                if not isinstance(name, str) or name == "UNKNOWN":
                    name = d.get("Mode", d.get("ModeNum"))
                if name is not None:
                    modes.append((ts, str(name)))

            elif mtype == "MSG":
                text = str(d.get("Message") or "")
                if firmware_version is None and text.startswith(tuple(_FIRMWARE_TO_VEHICLE_TYPE)):
                    firmware_version = text

            elif mtype == "ARM":
                if d.get("ArmState") is not None:
                    arm_msgs.append((ts, bool(d["ArmState"])))

            elif mtype == "EV":
                ev = d.get("Id")
                if ev in (EV_ARMED, EV_DISARMED):
                    arm_evs.append((ts, ev == EV_ARMED))
                elif ev in (EV_LAND_COMPLETE, EV_NOT_LANDED):
                    land.append((ts, ev == EV_LAND_COMPLETE))

        params = {k: float(v) for k, v in (getattr(reader, "params", None) or {}).items() if _is_numeric(v)}
        vehicle_type = _vehicle_type_from_firmware_string(firmware_version)
        t0 = first_us or 0
        topics: dict[str, pd.DataFrame] = {}

        accel, gyro = {}, None
        for i in sorted(imu):
            df = _frame(imu[i], ["timestamp", "rollspeed", "pitchspeed", "yawspeed", "x", "y", "z"])
            df["timestamp"] -= t0
            g = df[["timestamp", "rollspeed", "pitchspeed", "yawspeed"]].dropna(
                subset=["rollspeed", "pitchspeed", "yawspeed"], how="all")
            a = df[["timestamp", "x", "y", "z"]].dropna(subset=["x", "y", "z"], how="all")
            if gyro is None and not g.empty:
                gyro = g
            if not a.empty:
                accel[i] = a
        if gyro is not None:
            topics["vehicle_angular_velocity"] = gyro.reset_index(drop=True)
        store_instances(topics, "sensor_accel", accel)

        batteries = {}
        for i in sorted(bat):
            df = _frame(bat[i], [
                "timestamp", "voltage_v", "current_a", "temperature", "current_consumed_mah", "remaining"])
            df = df.dropna(subset=["voltage_v", "current_a"], how="all")
            if df.empty:
                continue
            df["timestamp"] -= t0
            # RemPct is the autopilot's own estimate (4.1+). Not derived from CurrTot
            # here: that would make the capacity-fade check compare a number with itself.
            if df["remaining"].notna().any():
                df["remaining"] = df["remaining"] / 100.0
            else:
                df = df.drop(columns="remaining")
            rated = params.get("BATT_CAPACITY" if i == 0 else f"BATT{i + 1}_CAPACITY")
            if rated and rated > 0:
                df["capacity"] = rated
            batteries[i] = df
        store_instances(topics, "battery_status", batteries)

        receivers = {}
        for i in sorted(gps):
            df = _frame(gps[i], [
                "timestamp", "lat", "lon", "alt", "satellites_used", "hdop", "fix_type"])
            # no fix value = not a usable GPS row
            df = df.dropna(subset=["lat", "lon", "fix_type"])
            if df.empty:
                continue
            df["timestamp"] -= t0
            # DFReader already scales Lat/Lng to degrees and Alt to metres;
            # the PX4 topic wants degE7 and mm. GPS Status uses the same 0-6 scale as fix_type.
            df["lat"] = (df["lat"] * 1e7).round().astype("int64")
            df["lon"] = (df["lon"] * 1e7).round().astype("int64")
            df["alt"] = (df["alt"] * 1000.0).round()
            df["fix_type"] = df["fix_type"].astype("int64")
            receivers[i] = df
        store_instances(topics, "vehicle_gps_position", receivers)

        esc_frames = {}
        for i in sorted(esc):
            df = _frame(esc[i], ["timestamp", "esc_rpm", "esc_voltage", "esc_current", "esc_temperature"])
            df = df.dropna(how="all", subset=["esc_rpm", "esc_voltage", "esc_current", "esc_temperature"])
            if not df.empty:
                df["timestamp"] -= t0
                esc_frames[i] = df
        if esc_frames:
            topics["esc_status"] = merge_esc(esc_frames)

        status, arm_count = _vehicle_status(arm_msgs or arm_evs, modes, vehicle_type, t0)
        if status is not None:
            topics["vehicle_status"] = status
        if land:
            topics["vehicle_land_detected"] = pd.DataFrame(
                [(ts - t0, v) for ts, v in sorted(land)], columns=["timestamp", "landed"])

        log_start_utc = None
        if gps_utc is not None:
            log_start_utc = utc_iso(gps_utc[1] - (gps_utc[0] - t0))

        duration_s = (last_us - first_us) / 1e6 if first_us is not None else 0.0
        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=firmware_version,
            vehicle_type=vehicle_type,
            log_start_utc=log_start_utc,
            arm_count=arm_count,
            flight_modes_used=sorted({name for _, name in modes}),
            available_topics=sorted(topics.keys()),
        )

        logger.info(
            f"Parsed ArduPilot log: {len(topics)} topics, {len(params)} params, "
            f"duration={duration_s:.1f}s"
        )
        return topics, params, metadata


def _vehicle_status(arm, modes, vehicle_type, t0):
    """vehicle_status rows from arm/disarm and mode changes; arming_state only when the
    log has any arm information. Returns (df or None, arm count)."""
    if not arm and not modes:
        return None, 0
    arm = sorted(arm)
    events = sorted([(ts, 0, v) for ts, v in arm] + [(ts, 1, v) for ts, v in modes], key=lambda e: e[:2])

    # before the first event the vehicle was in the opposite state
    armed = (not arm[0][1]) if arm else None
    nav = np.nan
    rows, count = [], 0
    if arm:
        rows.append((0, 2 if armed else 1, nav))
    for ts, kind, v in events:
        if kind == 0:
            if v and not armed:
                count += 1
            armed = v
        else:
            nav = ardupilot_nav_state(v, vehicle_type)
        rows.append((ts - t0, (2 if armed else 1) if armed is not None else np.nan, nav))

    df = pd.DataFrame(rows, columns=["timestamp", "arming_state", "nav_state"])
    if not arm:
        df = df.drop(columns="arming_state")
    else:
        df["arming_state"] = df["arming_state"].astype("int64")
    return df, count


def _is_numeric(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _vehicle_type_from_firmware_string(firmware_version: Optional[str]) -> Optional[str]:
    """The startup MSG line ("ArduCopter V4.3.5 (02ff7ea3)") is the only place a
    dataflash log records the vehicle type."""
    if not firmware_version:
        return None
    for prefix, vehicle_type in _FIRMWARE_TO_VEHICLE_TYPE.items():
        if prefix in firmware_version:
            return vehicle_type
    return None
