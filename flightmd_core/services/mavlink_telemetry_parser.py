"""
MAVLink telemetry log (.tlog) parser: the file QGroundControl and Mission Planner write
during a GCS-connected flight. Maps it onto the PX4 topic and column names (see
ulog_parser.py).

Only messages from the vehicle's autopilot (picked from its HEARTBEATs) are used, so a
GCS, gimbal or companion computer on the same link doesn't get mixed in. Timestamps are
vehicle time (time_boot_ms / time_usec), not the GCS receive time each record is
prefixed with: radio links deliver in bursts, and the receive time would put several
samples on the same microsecond.

estimator_status is deliberately not produced: EKF_STATUS_REPORT.flags uses the
ESTIMATOR_STATUS_FLAGS enum, which doesn't line up with PX4's solution_status_flags,
and a partial guess would produce EKF findings built on made-up bits.

A tlog runs at link rate, not log rate, so expect fewer findings than from the
onboard log of the same flight.
"""

import logging
import os
import struct
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import MIN_EPOCH_US, FlightMetadata, utc_iso
from flightmd_core.services.ardupilot_parser import ardupilot_nav_state, store_instances

logger = logging.getLogger(__name__)

# todo: ESC_STATUS / ESC_INFO aren't read yet, so tlogs never get motor data
WANTED_TYPES = [
    "BAD_DATA", "HEARTBEAT", "ATTITUDE", "RAW_IMU", "SCALED_IMU", "SCALED_IMU2",
    "SCALED_IMU3", "HIGHRES_IMU", "SYS_STATUS", "BATTERY_STATUS", "GPS_RAW_INT",
    "GPS2_RAW", "GLOBAL_POSITION_INT", "EXTENDED_SYS_STATE", "PARAM_VALUE",
]

MG = 0.00980665  # 1 milli-g in m/s^2
MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_AUTOPILOT_INVALID, MAV_AUTOPILOT_PX4 = 3, 8, 12
MAV_TYPE_GCS = 6
MAV_MODE_FLAG_SAFETY_ARMED = 128
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1

# boot clock going backwards by more than this = the vehicle rebooted
REBOOT_US = 1_000_000

VEHICLE_TYPES = {
    1: "Plane", 2: "Copter", 3: "Copter", 4: "Helicopter", 10: "Rover", 11: "Boat",
    12: "Sub", 13: "Copter", 14: "Copter", 15: "Copter",
    **{t: "VTOL" for t in range(19, 26)},
}

# PX4 custom_mode -> nav_state, from PX4's px4_custom_mode.h
PX4_MAIN_MODE = {1: 0, 2: 1, 3: 2, 5: 10, 6: 14, 7: 15, 8: 16}
PX4_AUTO_SUB_MODE = {2: 17, 3: 4, 4: 3, 5: 5, 6: 18, 7: 7, 8: 19, 9: 20, 10: 22}
PX4_POSCTL_SUB_MODE = {0: 2, 1: 21, 2: 6}

# PARAM_VALUE int types; PX4 sends their bytes inside the float (bytewise encoding)
PARAM_INT_FORMATS = {1: "<B", 2: "<b", 3: "<H", 4: "<h", 5: "<I", 6: "<i"}

COLUMNS = {
    "hb": ["type", "autopilot", "base_mode", "custom_mode"],
    "gyro": ["rollspeed", "pitchspeed", "yawspeed"],
    "accel": ["x", "y", "z"],
    "sys_bat": ["voltage_v", "current_a", "remaining"],
    "bat": ["voltage_v", "current_a", "temperature", "remaining", "current_consumed_mah"],
    "gps": ["lat", "lon", "alt", "fix_type", "satellites_used", "hdop", "eph"],
    "gpos": ["lat", "lon", "alt"],
    "ext": ["landed_state"],
}


def _scaled(v, k, unknown=()):
    return None if v is None or v in unknown else v * k


def _boot_usec(t):
    # time_usec is either epoch or time since boot; the size tells which
    return t if t and 0 < t < 1e15 else None


def _px4_nav_state(custom_mode: int) -> float:
    main, sub = (custom_mode >> 16) & 0xFF, (custom_mode >> 24) & 0xFF
    if main == 4:
        return PX4_AUTO_SUB_MODE.get(sub, np.nan)
    if main == 3:
        return PX4_POSCTL_SUB_MODE.get(sub, np.nan)
    return PX4_MAIN_MODE.get(main, np.nan)


def _vehicle_clock(frames: list[pd.DataFrame]) -> tuple[bool, int]:
    """
    Adds a 'timestamp' column (µs, still absolute) to every frame. Rows with a boot time
    get boot + the median receive-minus-boot offset of their boot segment; rows without
    one keep the receive time. Returns (had boot times, number of reboots).
    """
    refs = [f.loc[f["boot"].notna(), ["arrival", "boot"]] for f in frames]
    ref = pd.concat(refs).sort_values("arrival", kind="stable") if refs else pd.DataFrame()
    if ref.empty:
        for f in frames:
            f["timestamp"] = f["arrival"].astype("float64")
        return False, 0

    arr = ref["arrival"].to_numpy(dtype=float)
    boot = ref["boot"].to_numpy(dtype=float)
    seg = np.concatenate([[0], np.cumsum(np.diff(boot) < -REBOOT_US)])
    seg_off = pd.Series(arr - boot).groupby(seg).median().to_numpy()

    for f in frames:
        has = f["boot"].notna().to_numpy()
        a = f["arrival"].to_numpy(dtype=float)
        i = np.clip(np.searchsorted(arr, a, side="right") - 1, 0, len(arr) - 1)
        f["timestamp"] = np.where(has, f["boot"].to_numpy(dtype=float) + seg_off[seg[i]], a)
    return True, int(seg[-1])


class MavlinkTelemetryParser:
    """Same interface as ULogParser: .parse(path) -> (topics, params, metadata)."""

    def parse(
        self,
        tlog_path: str,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(tlog_path):
            raise FileNotFoundError(f"MAVLink telemetry log not found: {tlog_path}")

        from pymavlink import mavutil

        logger.info(f"Parsing MAVLink telemetry log: {tlog_path}")

        # mavlogfile directly: mavlink_connection() picks a reader from the extension
        # and would treat a temp file called x.log as a dataflash text log
        conn = mavutil.mavlogfile(tlog_path, robust_parsing=True)

        rows = defaultdict(list)
        raw_params = []
        bad = 0
        try:
            while True:
                msg = conn.recv_match(type=WANTED_TYPES)
                if msg is None:
                    break
                mtype = msg.get_type()
                if mtype == "BAD_DATA":
                    bad += 1
                    continue
                head = (msg.get_srcSystem(), msg.get_srcComponent(), int(msg._timestamp * 1e6))

                if mtype == "HEARTBEAT":
                    rows["hb"].append((*head, None, msg.type, msg.autopilot, msg.base_mode, msg.custom_mode))

                elif mtype == "ATTITUDE":
                    # rad/s, same as PX4's vehicle_angular_velocity
                    rows["gyro"].append((*head, msg.time_boot_ms * 1000, msg.rollspeed, msg.pitchspeed, msg.yawspeed))

                elif mtype.startswith("SCALED_IMU"):
                    inst = int(mtype[-1]) - 1 if mtype[-1].isdigit() else 0
                    rows[("accel", 1, inst)].append(
                        (*head, msg.time_boot_ms * 1000, msg.xacc * MG, msg.yacc * MG, msg.zacc * MG))

                elif mtype == "RAW_IMU":
                    # ArduPilot fills RAW_IMU w/ mG like SCALED_IMU
                    rows[("accel", 0, getattr(msg, "id", 0))].append(
                        (*head, _boot_usec(msg.time_usec), msg.xacc * MG, msg.yacc * MG, msg.zacc * MG))

                elif mtype == "HIGHRES_IMU":
                    rows[("accel", 2, getattr(msg, "id", 0))].append(
                        (*head, _boot_usec(msg.time_usec), msg.xacc, msg.yacc, msg.zacc))

                elif mtype == "SYS_STATUS":
                    rows["sys_bat"].append((
                        *head, None,
                        _scaled(msg.voltage_battery, 0.001, (0, 65535)),   # mV
                        _scaled(msg.current_battery, 0.01, (-1,)),         # cA
                        _scaled(msg.battery_remaining, 0.01, (-1,)),
                    ))

                elif mtype == "BATTERY_STATUS":
                    cells = list(msg.voltages) + list(getattr(msg, "voltages_ext", None) or [])
                    cells = [v for v in cells if 0 < v < 65535]  # mV, 65535 = no cell
                    rows[("bat", msg.id)].append((
                        *head, None,
                        sum(cells) / 1000 if cells else None,
                        _scaled(msg.current_battery, 0.01, (-1,)),
                        _scaled(msg.temperature, 0.01, (32767,)),          # cdegC
                        _scaled(msg.battery_remaining, 0.01, (-1,)),
                        _scaled(msg.current_consumed, 1, (-1,)),
                    ))

                elif mtype in ("GPS_RAW_INT", "GPS2_RAW"):
                    # lat/lon degE7 and alt mm already match PX4; eph is HDOP*100
                    h_acc = getattr(msg, "h_acc", 0)
                    rows[("gps", int(mtype == "GPS2_RAW"))].append((
                        *head, _boot_usec(msg.time_usec),
                        msg.lat, msg.lon, msg.alt, msg.fix_type,
                        _scaled(msg.satellites_visible, 1, (255,)),
                        _scaled(msg.eph, 0.01, (65535,)),
                        h_acc / 1000 if h_acc else None,
                    ))

                elif mtype == "GLOBAL_POSITION_INT":
                    # the EKF's postion, not the receiver's; no fix type
                    rows["gpos"].append((*head, msg.time_boot_ms * 1000, msg.lat / 1e7, msg.lon / 1e7, msg.alt / 1000))

                elif mtype == "EXTENDED_SYS_STATE":
                    rows["ext"].append((*head, None, msg.landed_state))

                elif mtype == "PARAM_VALUE":
                    raw_params.append((head[0], head[1], msg.param_id, msg.param_value, msg.param_type))
        finally:
            conn.close()

        frames = {}
        for key, data in rows.items():
            cols = COLUMNS[key if isinstance(key, str) else key[0]]
            df = pd.DataFrame(data, columns=["sys", "comp", "arrival", "boot", *cols])
            frames[key] = df.astype({c: "float64" for c in ["boot", *cols]})

        warnings = []
        if bad:
            warnings.append(f"{bad} unreadable chunks of the telemetry stream were skipped.")

        vehicle, autopilot, mav_type = _pick_vehicle(frames.get("hb"))
        if vehicle is None:
            warnings.append("No autopilot HEARTBEAT in this log, so messages from every system on the link were used.")
            # whatever heartbeats there are come from a GCS; they say nothing about arming
            frames.pop("hb", None)
        else:
            dropped = 0
            for key, df in list(frames.items()):
                mine = (df["sys"] == vehicle[0]) & (df["comp"] == vehicle[1])
                if key != "hb":
                    dropped += int((~mine).sum())
                frames[key] = df[mine].reset_index(drop=True)
            if dropped:
                warnings.append(f"Ignored {dropped} messages from other systems on the link (GCS, gimbal, companion computer).")
        frames = {k: f for k, f in frames.items() if not f.empty}

        had_boot, reboots = _vehicle_clock(list(frames.values()))
        if frames and not had_boot:
            warnings.append("No vehicle timestamps in this log; using the ground station's receive time, so rates and frequencies are approximate.")
        if reboots:
            warnings.append(f"The vehicle rebooted {reboots} time(s) during this log.")

        t0 = min((f["timestamp"].min() for f in frames.values()), default=0.0)
        t1 = max((f["timestamp"].max() for f in frames.values()), default=0.0)
        for f in frames.values():
            f["timestamp"] = (f["timestamp"] - t0).round().astype("int64")
            f.sort_values("timestamp", inplace=True, kind="stable")
            f.reset_index(drop=True, inplace=True)

        vehicle_kind = VEHICLE_TYPES.get(mav_type)
        topics = self._topics(frames, autopilot, vehicle_kind)
        status = topics.get("vehicle_status")
        modes = _mode_names(frames.get("hb"), autopilot, mav_type)

        arm_count = 0
        if status is not None:
            armed = (status["arming_state"] == 2).to_numpy(dtype=int)
            arm_count = int((np.diff(armed) == 1).sum())

        params = _decode_params(raw_params, vehicle, autopilot)
        duration_s = (t1 - t0) / 1e6
        # the receive clock is the GCS wall clock, close enough to UTC for a flight date
        log_start_utc = utc_iso(t0) if t0 > MIN_EPOCH_US else None

        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            vehicle_type=vehicle_kind,
            log_start_utc=log_start_utc,
            arm_count=arm_count,
            flight_modes_used=modes,
            available_topics=sorted(topics.keys()),
            parse_warnings=warnings,
        )

        logger.info(
            f"Parsed MAVLink telemetry log: {len(topics)} topics, {len(params)} params, "
            f"duration={duration_s:.1f}s"
        )
        return topics, params, metadata

    def _topics(self, frames, autopilot, vehicle_kind) -> dict[str, pd.DataFrame]:
        topics: dict[str, pd.DataFrame] = {}

        def cols(df, names):
            return df[["timestamp", *names]]

        if "gyro" in frames:
            gyro = cols(frames["gyro"], COLUMNS["gyro"]).dropna(subset=COLUMNS["gyro"], how="all")
            if not gyro.empty:
                topics["vehicle_angular_velocity"] = gyro.reset_index(drop=True)

        # one source per IMU: HIGHRES_IMU over SCALED_IMU over RAW_IMU
        accel = {}
        for key in sorted(k for k in frames if isinstance(k, tuple) and k[0] == "accel"):
            _, _, inst = key
            df = cols(frames[key], COLUMNS["accel"]).dropna(subset=COLUMNS["accel"], how="all")
            if not df.empty:
                accel[int(inst)] = df
        store_instances(topics, "sensor_accel", accel)

        batteries = {}
        for key in sorted(k for k in frames if isinstance(k, tuple) and k[0] == "bat"):
            df = cols(frames[key], COLUMNS["bat"]).dropna(subset=["voltage_v", "current_a"], how="all")
            if df["voltage_v"].notna().any():
                batteries[int(key[1])] = df
        if not batteries and "sys_bat" in frames:
            # SYS_STATUS only when there's no BATTERY_STATUS: mixing the two
            # interleaves rows that each have half the columns
            df = cols(frames["sys_bat"], COLUMNS["sys_bat"]).dropna(subset=["voltage_v", "current_a"], how="all")
            if not df.empty:
                batteries[0] = df
        store_instances(topics, "battery_status", batteries)

        receivers = {}
        for key in sorted(k for k in frames if isinstance(k, tuple) and k[0] == "gps"):
            df = cols(frames[key], COLUMNS["gps"]).dropna(subset=["lat", "lon", "fix_type"])
            if df.empty:
                continue
            df = df.astype({"lat": "int64", "lon": "int64", "fix_type": "int64"})
            if df["eph"].isna().all():
                df = df.drop(columns="eph")
            receivers[int(key[1])] = df
        store_instances(topics, "vehicle_gps_position", receivers)

        # kept apart from vehicle_gps_position: it has no fix_type / satellites / HDOP
        if "gpos" in frames:
            gpos = cols(frames["gpos"], COLUMNS["gpos"])
            gpos = gpos[(gpos["lat"] != 0) | (gpos["lon"] != 0)]
            if not gpos.empty:
                topics["vehicle_global_position"] = gpos.reset_index(drop=True)

        hb = frames.get("hb")
        if hb is not None:
            base = hb["base_mode"].astype("int64")
            custom = hb["custom_mode"].astype("int64")
            if autopilot == MAV_AUTOPILOT_PX4:
                nav = custom.map(_px4_nav_state)
            elif autopilot == MAV_AUTOPILOT_ARDUPILOTMEGA:
                frame = {"Helicopter": "Copter", "VTOL": "Plane"}.get(vehicle_kind, vehicle_kind)
                names = _ardupilot_names(custom, hb["type"])
                nav = pd.Series([ardupilot_nav_state(n, frame) for n in names], index=hb.index, dtype="float64")
            else:
                nav = pd.Series(np.nan, index=hb.index)
            nav = nav.where((base & MAV_MODE_FLAG_CUSTOM_MODE_ENABLED) != 0)
            topics["vehicle_status"] = pd.DataFrame({
                "timestamp": hb["timestamp"],
                "arming_state": np.where(base & MAV_MODE_FLAG_SAFETY_ARMED, 2, 1),
                "nav_state": nav.astype("float64"),
            })

        ext = frames.get("ext")
        if ext is not None:
            # MAV_LANDED_STATE: 0 unknown, 1 on ground, 2 in air, 3 taking off, 4 landing
            ext = ext[ext["landed_state"] > 0]
            if not ext.empty:
                topics["vehicle_land_detected"] = pd.DataFrame({
                    "timestamp": ext["timestamp"],
                    "landed": ext["landed_state"] == 1,
                }).reset_index(drop=True)

        return topics


def _pick_vehicle(hb: Optional[pd.DataFrame]):
    """(sys, comp), autopilot and MAV_TYPE of whoever sends the most autopilot heartbeats."""
    if hb is None:
        return None, None, None
    cand = hb[(hb["autopilot"] != MAV_AUTOPILOT_INVALID) & (hb["type"] != MAV_TYPE_GCS)]
    if cand.empty:
        return None, None, None
    sys_id, comp = cand.groupby(["sys", "comp"]).size().idxmax()
    mine = cand[(cand["sys"] == sys_id) & (cand["comp"] == comp)]
    return (sys_id, comp), int(mine["autopilot"].mode().iloc[0]), int(mine["type"].mode().iloc[0])


def _ardupilot_names(custom: pd.Series, mav_type: pd.Series) -> list[Optional[str]]:
    from pymavlink import mavutil

    out = []
    for c, t in zip(custom, mav_type):
        mapping = mavutil.mode_mapping_bynumber(int(t)) or {}
        out.append(mapping.get(int(c)))
    return out


def _mode_names(hb: Optional[pd.DataFrame], autopilot, mav_type) -> list[str]:
    if hb is None or hb.empty:
        return []
    hb = hb[(hb["base_mode"].astype("int64") & MAV_MODE_FLAG_CUSTOM_MODE_ENABLED) != 0]
    if autopilot == MAV_AUTOPILOT_PX4:
        from flightmd_core.services.ulog_parser import FLIGHT_MODE_NAMES

        nav = hb["custom_mode"].astype("int64").map(_px4_nav_state).dropna()
        return sorted({FLIGHT_MODE_NAMES.get(int(n), f"Mode {int(n)}") for n in nav})
    if autopilot == MAV_AUTOPILOT_ARDUPILOTMEGA:
        names = _ardupilot_names(hb["custom_mode"].astype("int64"), hb["type"])
        return sorted({n for n in names if n})
    return []


def _decode_params(raw, vehicle, autopilot) -> dict[str, float]:
    params: dict[str, float] = {}
    for sys_id, comp, pid, value, ptype in raw:
        if vehicle is not None and (sys_id, comp) != vehicle:
            continue
        if isinstance(pid, bytes):
            pid = pid.decode("ascii", "replace")
        pid = pid.split("\x00")[0]
        if not pid:
            continue
        fmt = PARAM_INT_FORMATS.get(ptype)
        if autopilot == MAV_AUTOPILOT_PX4 and fmt:
            raw_bytes = struct.pack("<f", value)[:struct.calcsize(fmt)]
            value = struct.unpack(fmt, raw_bytes)[0]
        try:
            params[pid] = float(value)
        except (TypeError, ValueError):
            pass
    return params
