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
and a partial guess would produce EKF findings built on made-up bits. The innovation
test ratios do line up, so they go to ekf_test_ratios (same columns as the .bin parser).

A tlog runs at link rate, not log rate, so expect fewer findings than from the
onboard log of the same flight.
"""

import logging
import os
import struct
from typing import Callable, Optional

import numpy as np
import pandas as pd

from flightmd_core.models.metadata import MIN_EPOCH_US, FlightMetadata, utc_iso
from flightmd_core.services.airframes import ardupilot_frame, px4_airframe
from flightmd_core.services.ardupilot_parser import (
    BOARD_LINE,
    _FIRMWARE_TO_VEHICLE_TYPE,
    ardupilot_nav_state,
    merge_esc,
    store_instances,
)
from flightmd_core.services.columns import ColumnBuffer

logger = logging.getLogger(__name__)

WANTED_TYPES = [
    "BAD_DATA", "HEARTBEAT", "ATTITUDE", "ATTITUDE_QUATERNION", "RAW_IMU", "SCALED_IMU",
    "SCALED_IMU2", "SCALED_IMU3", "HIGHRES_IMU", "SYS_STATUS", "BATTERY_STATUS",
    "GPS_RAW_INT", "GPS2_RAW", "GLOBAL_POSITION_INT", "EXTENDED_SYS_STATE", "PARAM_VALUE",
    "ESC_STATUS", "ESC_INFO", "ESC_TELEMETRY_1_TO_4", "ESC_TELEMETRY_5_TO_8",
    "ESC_TELEMETRY_9_TO_12", "VIBRATION", "EKF_STATUS_REPORT", "ESTIMATOR_STATUS",
    "POWER_STATUS", "HWSTATUS", "AUTOPILOT_VERSION", "STATUSTEXT",
]

MG = 0.00980665  # 1 milli-g in m/s^2
MAV_AUTOPILOT_ARDUPILOTMEGA, MAV_AUTOPILOT_INVALID, MAV_AUTOPILOT_PX4 = 3, 8, 12
MAV_TYPE_GCS = 6
MAV_MODE_FLAG_SAFETY_ARMED = 128
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1

# boot clock going backwards by more than this = the vehicle rebooted
REBOOT_US = 1_000_000

PROGRESS_EVERY = 20_000  # messages

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

CELLS = 14  # BATTERY_STATUS voltages[10] + voltages_ext[4]

COLUMNS = {
    "hb": ["type", "autopilot", "base_mode", "custom_mode"],
    "gyro": ["rollspeed", "pitchspeed", "yawspeed"],
    "gyro_q": ["rollspeed", "pitchspeed", "yawspeed"],
    "accel": ["x", "y", "z"],
    "sys_bat": ["voltage_v", "current_a", "remaining"],
    "bat": ["voltage_v", "current_a", "temperature", "remaining", "current_consumed_mah",
            *(f"cell{k}" for k in range(CELLS))],
    "gps": ["lat", "lon", "alt", "fix_type", "satellites_used", "hdop", "eph", "epv", "s_variance_m_s"],
    "gpos": ["lat", "lon", "alt"],
    "ext": ["landed_state"],
    "esc": ["esc_rpm", "esc_voltage", "esc_current", "esc_temperature"],
    "esc_info": ["count", "esc_temperature"],
    "vib": ["vibration_x", "vibration_y", "vibration_z", "clipping_0", "clipping_1", "clipping_2"],
    "ekf_ap": ["flags", "vel", "pos", "hgt", "mag", "hagl", "tas"],
    "ekf_px4": ["flags", "vel", "pos", "hgt", "mag", "hagl", "tas"],
    "power": ["voltage5v_v", "servo_rail_v", "power_flags"],
    "hwstatus": ["voltage5v_v"],
}


def _scaled(v, k, unknown=()):
    return None if v is None or v in unknown else v * k


def _boot_usec(t):
    # time_usec is either epoch or time since boot; the size tells which
    return t if t and 0 < t < 1e15 else None


def _text(v) -> str:
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", "replace")
    return str(v or "").split("\x00")[0].strip()


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
        progress: Optional[Callable[[float], None]] = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        """progress, if given, is called now and then with the fraction done (0-1)."""
        if not os.path.exists(tlog_path):
            raise FileNotFoundError(f"MAVLink telemetry log not found: {tlog_path}")

        from pymavlink import mavutil

        logger.info(f"Parsing MAVLink telemetry log: {tlog_path}")

        # mavlogfile directly: mavlink_connection() picks a reader from the extension
        # and would treat a temp file called x.log as a dataflash text log
        conn = mavutil.mavlogfile(tlog_path, robust_parsing=True)

        # no index to size these from, so they grow as they go
        bufs: dict = {}

        def add(key, row):
            buf = bufs.get(key)
            if buf is None:
                cols = COLUMNS[key if isinstance(key, str) else key[0]]
                buf = bufs[key] = ColumnBuffer(["sys", "comp", "arrival", "boot", *cols])
            buf.append(row)

        raw_params, texts = [], []
        bad = n = 0
        try:
            while True:
                msg = conn.recv_match(type=WANTED_TYPES)
                if msg is None:
                    break
                n += 1
                if progress is not None and n % PROGRESS_EVERY == 0:
                    pct = getattr(conn, "percent", None)
                    if pct is not None:
                        progress(pct / 100)

                mtype = msg.get_type()
                if mtype == "BAD_DATA":
                    bad += 1
                    continue
                head = (msg.get_srcSystem(), msg.get_srcComponent(), int(msg._timestamp * 1e6))

                if mtype == "HEARTBEAT":
                    add("hb", (*head, None, msg.type, msg.autopilot, msg.base_mode, msg.custom_mode))

                elif mtype == "ATTITUDE":
                    # rad/s, same as PX4's vehicle_angular_velocity
                    add("gyro", (*head, msg.time_boot_ms * 1000, msg.rollspeed, msg.pitchspeed, msg.yawspeed))

                elif mtype == "ATTITUDE_QUATERNION":
                    add("gyro_q", (*head, msg.time_boot_ms * 1000, msg.rollspeed, msg.pitchspeed, msg.yawspeed))

                elif mtype.startswith("SCALED_IMU"):
                    inst = int(mtype[-1]) - 1 if mtype[-1].isdigit() else 0
                    add(("accel", 1, inst),
                        (*head, msg.time_boot_ms * 1000, msg.xacc * MG, msg.yacc * MG, msg.zacc * MG))

                elif mtype == "RAW_IMU":
                    # ArduPilot fills RAW_IMU w/ mG like SCALED_IMU
                    add(("accel", 0, getattr(msg, "id", 0)),
                        (*head, _boot_usec(msg.time_usec), msg.xacc * MG, msg.yacc * MG, msg.zacc * MG))

                elif mtype == "HIGHRES_IMU":
                    add(("accel", 2, getattr(msg, "id", 0)),
                        (*head, _boot_usec(msg.time_usec), msg.xacc, msg.yacc, msg.zacc))

                elif mtype == "SYS_STATUS":
                    add("sys_bat", (
                        *head, None,
                        _scaled(msg.voltage_battery, 0.001, (0, 65535)),   # mV
                        _scaled(msg.current_battery, 0.01, (-1,)),         # cA
                        _scaled(msg.battery_remaining, 0.01, (-1,)),
                    ))

                elif mtype == "BATTERY_STATUS":
                    cells = list(msg.voltages) + list(getattr(msg, "voltages_ext", None) or [])
                    # mV; 65535 = no cell (and 0 in voltages_ext)
                    cells = [v / 1000 if 0 < v < 65535 else None for v in cells][:CELLS]
                    live = [v for v in cells if v is not None]
                    add(("bat", msg.id), (
                        *head, None,
                        sum(live) if live else None,
                        _scaled(msg.current_battery, 0.01, (-1,)),
                        _scaled(msg.temperature, 0.01, (32767,)),          # cdegC
                        _scaled(msg.battery_remaining, 0.01, (-1,)),
                        _scaled(msg.current_consumed, 1, (-1,)),
                        *cells, *([None] * (CELLS - len(cells))),
                    ))

                elif mtype in ("GPS_RAW_INT", "GPS2_RAW"):
                    # lat/lon degE7 and alt mm already match PX4; eph is HDOP*100
                    h_acc = getattr(msg, "h_acc", 0)
                    v_acc = getattr(msg, "v_acc", 0)
                    vel_acc = getattr(msg, "vel_acc", 0)
                    add(("gps", int(mtype == "GPS2_RAW")), (
                        *head, _boot_usec(msg.time_usec),
                        msg.lat, msg.lon, msg.alt, msg.fix_type,
                        _scaled(msg.satellites_visible, 1, (255,)),
                        _scaled(msg.eph, 0.01, (65535,)),
                        h_acc / 1000 if h_acc else None,     # mm
                        v_acc / 1000 if v_acc else None,
                        vel_acc / 1000 if vel_acc else None,  # mm/s
                    ))

                elif mtype == "GLOBAL_POSITION_INT":
                    # the EKF's postion, not the receiver's; no fix type
                    add("gpos", (*head, msg.time_boot_ms * 1000, msg.lat / 1e7, msg.lon / 1e7, msg.alt / 1000))

                elif mtype == "EXTENDED_SYS_STATE":
                    add("ext", (*head, None, msg.landed_state))

                elif mtype == "ESC_STATUS":
                    for k in range(4):
                        add(("esc", msg.index + k), (
                            *head, _boot_usec(msg.time_usec),
                            msg.rpm[k], msg.voltage[k], msg.current[k], None))

                elif mtype == "ESC_INFO":
                    for k in range(4):
                        add(("esc_info", msg.index + k), (
                            *head, _boot_usec(msg.time_usec),
                            msg.count, _scaled(msg.temperature[k], 0.01, (32767,))))

                elif mtype.startswith("ESC_TELEMETRY_"):
                    first = int(mtype.split("_")[2]) - 1
                    for k in range(4):
                        # ArduPilot: degC, cV, cA; no timestamp in the message
                        add(("esc", first + k), (
                            *head, None, msg.rpm[k], msg.voltage[k] / 100, msg.current[k] / 100,
                            msg.temperature[k]))

                elif mtype == "VIBRATION":
                    add("vib", (*head, _boot_usec(msg.time_usec), msg.vibration_x, msg.vibration_y,
                                msg.vibration_z, msg.clipping_0, msg.clipping_1, msg.clipping_2))

                elif mtype == "EKF_STATUS_REPORT":
                    add("ekf_ap", (*head, None, msg.flags, msg.velocity_variance, msg.pos_horiz_variance,
                                   msg.pos_vert_variance, msg.compass_variance, msg.terrain_alt_variance,
                                   getattr(msg, "airspeed_variance", None)))

                elif mtype == "ESTIMATOR_STATUS":
                    add("ekf_px4", (*head, _boot_usec(msg.time_usec), msg.flags, msg.vel_ratio,
                                    msg.pos_horiz_ratio, msg.pos_vert_ratio, msg.mag_ratio,
                                    msg.hagl_ratio, msg.tas_ratio))

                elif mtype == "POWER_STATUS":
                    add("power", (*head, None, msg.Vcc / 1000, msg.Vservo / 1000, msg.flags))

                elif mtype == "HWSTATUS":
                    add("hwstatus", (*head, None, msg.Vcc / 1000))

                elif mtype == "AUTOPILOT_VERSION":
                    texts.append((head[0], head[1], "version", msg.flight_sw_version))

                elif mtype == "STATUSTEXT":
                    texts.append((head[0], head[1], "text", _text(msg.text)))

                elif mtype == "PARAM_VALUE":
                    raw_params.append((head[0], head[1], msg.param_id, msg.param_value, msg.param_type))
        finally:
            conn.close()

        frames = {key: b.frame() for key, b in bufs.items()}

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
            texts = [t for t in texts if (t[0], t[1]) == vehicle]
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

        firmware, px4_version, board, frame_text = _firmware(texts, autopilot)
        if vehicle_kind is None and firmware:
            vehicle_kind = next((v for k, v in _FIRMWARE_TO_VEHICLE_TYPE.items() if k in firmware), None)

        airframe_id = airframe_name = None
        if autopilot == MAV_AUTOPILOT_PX4 and "SYS_AUTOSTART" in params:
            airframe_id = int(params["SYS_AUTOSTART"])
            airframe_name, _ = px4_airframe(airframe_id)
        elif autopilot == MAV_AUTOPILOT_ARDUPILOTMEGA:
            frame = {"Helicopter": "Copter", "Boat": "Rover"}.get(vehicle_kind, vehicle_kind)
            airframe_name = ardupilot_frame(params, frame) or frame_text

        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=firmware,
            px4_version=px4_version,
            hardware_id=board,
            airframe_id=airframe_id,
            airframe_name=airframe_name,
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

        # PX4 can stream ATTITUDE_QUATERNION instead of ATTITUDE; both have the rates
        src = "gyro" if "gyro" in frames else "gyro_q"
        if src in frames:
            gyro = cols(frames[src], COLUMNS["gyro"]).dropna(subset=COLUMNS["gyro"], how="all")
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
                batteries[int(key[1])] = _cells(df)
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
            df = df.drop(columns=[c for c in ("eph", "epv", "s_variance_m_s") if df[c].isna().all()])
            receivers[int(key[1])] = df
        store_instances(topics, "vehicle_gps_position", receivers)

        # kept apart from vehicle_gps_position: it has no fix_type / satellites / HDOP
        if "gpos" in frames:
            gpos = cols(frames["gpos"], COLUMNS["gpos"])
            gpos = gpos[(gpos["lat"] != 0) | (gpos["lon"] != 0)]
            if not gpos.empty:
                topics["vehicle_global_position"] = gpos.reset_index(drop=True)

        esc = _esc_status(frames)
        if esc is not None:
            topics["esc_status"] = esc

        vib = frames.get("vib")
        if vib is not None:
            if autopilot == MAV_AUTOPILOT_PX4:
                # PX4 fills VIBRATION with its own metrics, not the spec's
                # (mavlink/streams/VIBRATION.hpp); clipping_k is a different count too
                topics["vehicle_imu_status"] = pd.DataFrame({
                    "timestamp": vib["timestamp"],
                    "accel_vibration_metric": vib["vibration_z"],
                    "gyro_vibration_metric": vib["vibration_y"],
                    "delta_angle_coning_metric": vib["vibration_x"],
                })
            else:
                topics["vibration"] = cols(vib, COLUMNS["vib"]).reset_index(drop=True)

        # PX4 sends ESTIMATOR_STATUS (plain test ratios); ArduPilot EKF_STATUS_REPORT,
        # whose "variances" are the square roots of the same ratios
        ekf = frames.get("ekf_px4")
        squared = False
        if ekf is None:
            ekf, squared = frames.get("ekf_ap"), True
        if ekf is not None:
            out = pd.DataFrame({"timestamp": ekf["timestamp"]})
            for c in ["vel", "pos", "hgt", "mag", "tas", "hagl"]:
                if ekf[c].notna().any():
                    out[f"{c}_test_ratio"] = ekf[c] ** 2 if squared else ekf[c]
            out["flags"] = ekf["flags"]
            topics["ekf_test_ratios"] = out

        power = frames.get("power")
        if power is None and "hwstatus" in frames:
            power = frames["hwstatus"]
        if power is not None:
            topics["system_power"] = power.drop(columns=["sys", "comp", "arrival", "boot"]).reset_index(drop=True)

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


def _cells(bat: pd.DataFrame) -> pd.DataFrame:
    """cell0..13 -> voltage_cell_v[k] for the cells that report, plus cell_count."""
    raw = [f"cell{k}" for k in range(CELLS)]
    live = [c for c in raw if bat[c].notna().any()]
    out = bat.drop(columns=raw)
    if live:
        for k, c in enumerate(live):
            out[f"voltage_cell_v[{k}]"] = bat[c]
        out["cell_count"] = len(live)
    return out


def _esc_status(frames) -> Optional[pd.DataFrame]:
    """ESC_STATUS / ESC_TELEMETRY_x_TO_y per ESC, merged like the .bin ESC messages.

    Both always carry 4 slots. ESC_INFO.count says how many ESCs are real; without it,
    an ESC that never reports anything but zeros is an empty slot.
    """
    per_esc = {}
    for key in sorted(k for k in frames if isinstance(k, tuple) and k[0] == "esc"):
        df = frames[key][["timestamp", *COLUMNS["esc"]]]
        per_esc[int(key[1])] = df.dropna(how="all", subset=COLUMNS["esc"])
    if not per_esc:
        return None

    info = {int(k[1]): f for k, f in frames.items() if isinstance(k, tuple) and k[0] == "esc_info"}
    counts = [f["count"].max() for f in info.values() if f["count"].notna().any()]
    if counts and max(counts) > 0:
        n = int(max(counts))
    else:
        live = [i for i, df in per_esc.items() if df[COLUMNS["esc"]].fillna(0).ne(0).any().any()]
        n = max(live) + 1 if live else 0
    per_esc = {i: df for i, df in per_esc.items() if i < n and not df.empty}
    if not per_esc:
        return None

    out = merge_esc(per_esc)
    out["esc_count"] = n
    # ESC_INFO is the only temperature source on PX4
    for i, f in info.items():
        col = f"esc[{i}].esc_temperature"
        if i >= n or col not in out.columns or f["esc_temperature"].isna().all():
            continue
        if out[col].notna().any():
            continue
        temps = f[["timestamp", "esc_temperature"]].dropna().sort_values("timestamp")
        merged = pd.merge_asof(out[["timestamp"]], temps, on="timestamp", direction="nearest",
                               tolerance=2_000_000)
        out[col] = merged["esc_temperature"].to_numpy()
    return out


def _firmware(texts, autopilot):
    """(firmware string, px4 version, board, ArduPilot "Frame:" text) from
    AUTOPILOT_VERSION and the startup STATUSTEXTs."""
    from flightmd_core.services.ulog_parser import _px4_release

    banner = board = frame_text = release = None
    for _, _, kind, value in texts:
        if kind == "version":
            if release is None and value:
                release = _px4_release(value)
        elif banner is None and value.startswith(tuple(_FIRMWARE_TO_VEHICLE_TYPE)):
            banner = value
        elif board is None and (m := BOARD_LINE.match(value)):
            board = m.group(1)
        elif frame_text is None and value.startswith("Frame: "):
            frame_text = value[len("Frame: "):].strip()

    px4_version = release if autopilot == MAV_AUTOPILOT_PX4 else None
    if banner:
        firmware = banner
    elif release:
        firmware = f"{'PX4' if autopilot == MAV_AUTOPILOT_PX4 else 'ArduPilot'} {release}"
    else:
        firmware = None
    return firmware, px4_version, board, frame_text


def _pick_vehicle(hb: Optional[pd.DataFrame]):
    """(sys, comp), autopilot and MAV_TYPE of whoever sends the most autopilot heartbeats."""
    if hb is None:
        return None, None, None
    cand = hb[(hb["autopilot"] != MAV_AUTOPILOT_INVALID) & (hb["type"] != MAV_TYPE_GCS)]
    if cand.empty:
        return None, None, None
    sys_id, comp = cand.groupby(["sys", "comp"]).size().idxmax()
    mine = cand[(cand["sys"] == sys_id) & (cand["comp"] == comp)]
    return (int(sys_id), int(comp)), int(mine["autopilot"].mode().iloc[0]), int(mine["type"].mode().iloc[0])


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
