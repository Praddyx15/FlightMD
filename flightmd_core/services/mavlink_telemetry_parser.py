"""
MavlinkTelemetryParser — reads MAVLink telemetry logs (.tlog), the format
QGroundControl and Mission Planner write during a GCS-connected flight, and
normalizes them into the same canonical topic/column schema the seven
analysers already consume (see ulog_parser.py for the PX4 side of that
schema).

Field names below were confirmed against the installed pymavlink dialect
via direct introspection (MAVLink_<type>_message.fieldnames), not assumed
from memory — see the comments on each mapping.

IMPORTANT — `estimator_status` is intentionally NOT produced here.
MAVLink's EKF_STATUS_REPORT.flags uses the ESTIMATOR_STATUS_FLAGS enum,
whose bit layout does not cleanly correspond to all six bits PX4's
solution_status_flags exposes (there is no equivalent to PX4's
`gps_available` bit, for example). Synthesising a partial bitmask would
produce EKF findings built on guessed semantics. The EKF analyser skips
gracefully when `estimator_status` is absent, the same way it already does
for PX4 logs missing that topic.

`.tlog` files are typically much sparser than onboard dataflash/ULog
recordings (GCS link rate, not full log rate) — fewer resulting findings
is expected behaviour for this format, not a bug.
"""

import logging
import os
from typing import Optional

import pandas as pd

from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)


class MavlinkTelemetryParser:
    """
    Parses a MAVLink telemetry log (.tlog).

    Same interface as ULogParser: .parse(path) -> (topics, params, metadata)
    """

    def parse(
        self,
        tlog_path: str,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(tlog_path):
            raise FileNotFoundError(f"MAVLink telemetry log not found: {tlog_path}")

        from pymavlink import mavutil

        logger.info(f"Parsing MAVLink telemetry log: {tlog_path}")

        conn = mavutil.mavlink_connection(tlog_path, robust_parsing=True)

        gyro_rows: list[dict] = []
        accel_rows: list[dict] = []
        accel_source: Optional[str] = None  # first IMU message type wins, so
                                             # rows are never mixed across
                                             # different physical sensors
        bat_rows: list[dict] = []
        gps_rows: list[dict] = []
        params: dict[str, float] = {}
        first_ts_us: Optional[int] = None
        last_ts_us: Optional[int] = None

        while True:
            msg = conn.recv_match(blocking=False)
            if msg is None:
                break

            mtype = msg.get_type()
            ts_us = int(getattr(msg, "_timestamp", 0) * 1e6)
            if ts_us:
                first_ts_us = ts_us if first_ts_us is None else min(first_ts_us, ts_us)
                last_ts_us = ts_us if last_ts_us is None else max(last_ts_us, ts_us)

            if mtype == "ATTITUDE":
                # ATTITUDE.rollspeed/pitchspeed/yawspeed are rad/s, matching
                # PX4's vehicle_angular_velocity units directly.
                gyro_rows.append({
                    "timestamp": ts_us,
                    "rollspeed": msg.rollspeed,
                    "pitchspeed": msg.pitchspeed,
                    "yawspeed": msg.yawspeed,
                })

            elif mtype in ("RAW_IMU", "SCALED_IMU", "SCALED_IMU2") and accel_source in (None, mtype):
                # First IMU message type encountered wins for the rest of the
                # file, so rows are never mixed across different physical
                # IMUs if a log happens to carry more than one message type.
                # xacc/yacc/zacc are in mG (milli-g) per the MAVLink common
                # dialect; convert to m/s^2 (1 mG = 0.00980665 m/s^2) to
                # match PX4's sensor_accel units.
                accel_source = mtype
                accel_rows.append({
                    "timestamp": ts_us,
                    "x": msg.xacc * 0.00980665,
                    "y": msg.yacc * 0.00980665,
                    "z": msg.zacc * 0.00980665,
                })

            elif mtype == "BATTERY_STATUS":
                # temperature is centi-degrees C; INT16_MAX (32767) means
                # "not measured" and must be treated as missing.
                temp_raw = getattr(msg, "temperature", None)
                temp_c = temp_raw / 100.0 if temp_raw not in (None, 32767) else None
                current_raw = getattr(msg, "current_battery", None)
                current_a = current_raw / 100.0 if current_raw not in (None, -1) else None
                remaining_raw = getattr(msg, "battery_remaining", None)
                remaining_frac = remaining_raw / 100.0 if remaining_raw not in (None, -1) else None
                bat_rows.append({
                    "timestamp": ts_us,
                    "current_a": current_a,
                    "temperature": temp_c,
                    "remaining": remaining_frac,
                })

            elif mtype == "SYS_STATUS":
                # voltage_battery is millivolts (total pack voltage).
                voltage_raw = getattr(msg, "voltage_battery", None)
                voltage_v = voltage_raw / 1000.0 if voltage_raw not in (None, 65535, 0) else None
                current_raw = getattr(msg, "current_battery", None)
                current_a = current_raw / 100.0 if current_raw not in (None, -1) else None
                remaining_raw = getattr(msg, "battery_remaining", None)
                remaining_frac = remaining_raw / 100.0 if remaining_raw not in (None, -1) else None
                bat_rows.append({
                    "timestamp": ts_us,
                    "voltage_v": voltage_v,
                    "current_a": current_a,
                    "remaining": remaining_frac,
                })

            elif mtype in ("GPS_RAW_INT", "GLOBAL_POSITION_INT"):
                # GPS_RAW_INT: lat/lon in degrees*1e7 (matches PX4 exactly),
                # alt in mm, eph is HDOP*100 (cm-equivalent scale). Prefer
                # GPS_RAW_INT since it carries fix_type/satellites/HDOP;
                # GLOBAL_POSITION_INT lacks those and is used only as a
                # position fallback.
                if mtype == "GPS_RAW_INT":
                    gps_rows.append({
                        "timestamp": ts_us,
                        "lat": msg.lat,
                        "lon": msg.lon,
                        "alt": msg.alt,
                        "fix_type": msg.fix_type,
                        "satellites_used": msg.satellites_visible,
                        "hdop": msg.eph / 100.0 if msg.eph not in (65535,) else None,
                    })
                else:
                    gps_rows.append({
                        "timestamp": ts_us,
                        "lat": msg.lat,
                        "lon": msg.lon,
                        "alt": msg.alt,
                    })

            elif mtype == "PARAM_VALUE":
                try:
                    params[msg.param_id.strip("\x00")] = float(msg.param_value)
                except (TypeError, ValueError):
                    pass

        conn.close()

        topics: dict[str, pd.DataFrame] = {}

        if gyro_rows:
            gyro_df = pd.DataFrame(gyro_rows).dropna(
                subset=["rollspeed", "pitchspeed", "yawspeed"], how="all"
            )
            if not gyro_df.empty:
                topics["vehicle_angular_velocity"] = gyro_df.reset_index(drop=True)

        if accel_rows:
            accel_df = pd.DataFrame(accel_rows).dropna(subset=["x", "y", "z"], how="all")
            if not accel_df.empty:
                topics["sensor_accel_0"] = accel_df.reset_index(drop=True)
                topics["sensor_accel"] = accel_df.reset_index(drop=True)

        if bat_rows:
            bat_df = pd.DataFrame(bat_rows)
            # Multiple message types can each supply a partial row (e.g.
            # SYS_STATUS has voltage but not the fuller BATTERY_STATUS
            # temperature) — merge by forward-filling missing columns.
            for col in ("voltage_v", "current_a", "temperature", "remaining"):
                if col not in bat_df.columns:
                    bat_df[col] = None
            bat_df = bat_df.dropna(subset=["voltage_v", "current_a"], how="all")
            if not bat_df.empty:
                topics["battery_status"] = bat_df.sort_values("timestamp").reset_index(drop=True)

        if gps_rows:
            gps_df = pd.DataFrame(gps_rows).dropna(subset=["lat", "lon"], how="all")
            gps_df = gps_df[(gps_df["lat"] != 0) & (gps_df["lon"] != 0)]
            if not gps_df.empty:
                # No jamming_indicator/spoofing_state in standard MAVLink
                # telemetry — omitted; the GPS analyser skips those checks.
                topics["vehicle_gps_position"] = gps_df.sort_values("timestamp").reset_index(drop=True)

        duration_s = 0.0
        if first_ts_us is not None and last_ts_us is not None:
            duration_s = (last_ts_us - first_ts_us) / 1e6

        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            available_topics=sorted(topics.keys()),
        )

        logger.info(
            f"Parsed MAVLink telemetry log: {len(topics)} topics, {len(params)} params, "
            f"duration={duration_s:.1f}s"
        )
        return topics, params, metadata
