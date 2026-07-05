"""
ArduPilotBinParser — reads ArduPilot dataflash (.bin) logs via pymavlink's
DFReader and normalizes them into the same canonical topic/column schema
the seven analysers already consume (see ulog_parser.py for the PX4 side of
that schema). This lets every analyser run unmodified against ArduPilot logs.

IMPORTANT — what is intentionally NOT mapped here:

`estimator_status` (EKF innovation/solution bitmasks) is not produced by
this parser. ArduPilot's EKF3/XKF dataflash messages use different field
names and different bit semantics than PX4's `innovation_check_flags` /
`solution_status_flags`, and field names additionally vary across ArduPilot
firmware versions (EKF3 vs XKF1/NKF1). Fabricating a best-guess bitmask
would produce EKF findings that look precise but may not correspond to
what the aircraft's estimator actually reported. Until this mapping is
verified field-by-field against a real ArduPilot sample log (see
tests/sample_logs/README.md), the EKF analyser is left to skip gracefully
for ArduPilot logs, the same way it already skips for PX4 logs missing
`estimator_status`.

ESC telemetry mapping is similarly best-effort — only included when the
log actually contains an `ESC` message; if firmware/field names differ,
the motor analyser's existing "no ESC RPM columns found" skip path applies.
"""

import logging
import os
from collections import defaultdict
from typing import Optional

import pandas as pd

from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)


def _get_field(msg, *names):
    """Return the first present field value from a DFMessage-like object,
    trying each candidate name in order. Returns None if none are present.
    ArduPilot field names vary by firmware version, so callers pass multiple
    aliases (mirrors the _find_col alias pattern used by ULogParser/analysers)."""
    d = msg.to_dict() if hasattr(msg, "to_dict") else vars(msg)
    for name in names:
        if name in d and d[name] is not None:
            return d[name]
    return None


def _msg_timestamp_us(msg) -> int:
    """
    DFReader normalizes every message's arrival time onto a `_timestamp`
    attribute (seconds, via its init_clock_* methods) regardless of which
    onboard clock source the log used. Convert to microseconds to match the
    PX4 ULog convention the analysers expect.
    """
    ts = getattr(msg, "_timestamp", None)
    return int(ts * 1e6) if ts else 0


class ArduPilotBinParser:
    """
    Parses an ArduPilot dataflash (.bin) log.

    Same interface as ULogParser: .parse(path) -> (topics, params, metadata)
    """

    def parse(
        self,
        bin_path: str,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        if not os.path.exists(bin_path):
            raise FileNotFoundError(f"ArduPilot log file not found: {bin_path}")

        from pymavlink import DFReader

        logger.info(f"Parsing ArduPilot dataflash log: {bin_path}")

        reader = DFReader.DFReader_binary(bin_path)

        imu_rows: dict[int, list[dict]] = defaultdict(list)
        bat_rows: list[dict] = []
        gps_rows: list[dict] = []
        esc_rows: dict[int, list[dict]] = defaultdict(list)
        mode_changes: list[str] = []
        arm_events = 0
        was_armed = False
        firmware_version = None
        first_ts_us: Optional[int] = None
        last_ts_us: Optional[int] = None

        while True:
            msg = reader.recv_msg()
            if msg is None:
                break

            mtype = msg.get_type()
            ts_us = _msg_timestamp_us(msg)
            if ts_us:
                first_ts_us = ts_us if first_ts_us is None else min(first_ts_us, ts_us)
                last_ts_us = ts_us if last_ts_us is None else max(last_ts_us, ts_us)

            if mtype in ("IMU", "IMU2", "IMU3"):
                instance = _get_field(msg, "I", "IMU") or 0
                gyr_x = _get_field(msg, "GyrX")
                gyr_y = _get_field(msg, "GyrY")
                gyr_z = _get_field(msg, "GyrZ")
                acc_x = _get_field(msg, "AccX")
                acc_y = _get_field(msg, "AccY")
                acc_z = _get_field(msg, "AccZ")
                imu_rows[int(instance)].append({
                    "timestamp": ts_us,
                    "rollspeed": gyr_x, "pitchspeed": gyr_y, "yawspeed": gyr_z,
                    "x": acc_x, "y": acc_y, "z": acc_z,
                })

            elif mtype == "BAT":
                bat_rows.append({
                    "timestamp": ts_us,
                    "voltage_v": _get_field(msg, "Volt", "VoltR"),
                    "current_a": _get_field(msg, "Curr"),
                    "temperature": _get_field(msg, "Temp"),
                    "current_consumed_mah": _get_field(msg, "CurrTot"),
                })

            elif mtype == "GPS":
                gps_rows.append({
                    "timestamp": ts_us,
                    "lat": _get_field(msg, "Lat"),
                    "lon": _get_field(msg, "Lng", "Lon"),
                    "alt": _get_field(msg, "Alt"),
                    "satellites_used": _get_field(msg, "NSats"),
                    "hdop": _get_field(msg, "HDop"),
                    "fix_type": _get_field(msg, "Status"),
                })

            elif mtype == "ESC":
                instance = _get_field(msg, "Instance", "I") or 0
                esc_rows[int(instance)].append({
                    "timestamp": ts_us,
                    "rpm": _get_field(msg, "RPM"),
                    "current": _get_field(msg, "Curr"),
                    "temperature": _get_field(msg, "Temp"),
                })

            elif mtype == "MODE":
                mode_name = _get_field(msg, "Mode", "ModeNum")
                if mode_name is not None:
                    mode_changes.append(str(mode_name))

            elif mtype in ("MSG",):
                text = _get_field(msg, "Message")
                if text and firmware_version is None and ("ArduCopter" in str(text) or "ArduPlane" in str(text) or "V" in str(text)):
                    firmware_version = str(text)

            elif mtype == "EV":
                # ArduPilot logs a discrete event ID for arm/disarm transitions.
                # Event IDs 10/11 = ARMED/DISARMED in ArduPilot's DataFlash log
                # event table; verify against a real log before relying on this.
                ev_id = _get_field(msg, "Id")
                if ev_id == 10 and not was_armed:
                    arm_events += 1
                    was_armed = True
                elif ev_id == 11:
                    was_armed = False

        params = dict(reader.params) if hasattr(reader, "params") and reader.params else {}
        params = {k: float(v) for k, v in params.items() if _is_numeric(v)}

        topics: dict[str, pd.DataFrame] = {}

        for instance, rows in imu_rows.items():
            df = pd.DataFrame(rows).dropna(how="all", subset=["rollspeed", "pitchspeed", "yawspeed", "x", "y", "z"])
            if df.empty:
                continue
            gyro_df = df[["timestamp", "rollspeed", "pitchspeed", "yawspeed"]].dropna(
                subset=["rollspeed", "pitchspeed", "yawspeed"], how="all"
            )
            accel_df = df[["timestamp", "x", "y", "z"]].dropna(subset=["x", "y", "z"], how="all")
            if not gyro_df.empty and "vehicle_angular_velocity" not in topics:
                topics["vehicle_angular_velocity"] = gyro_df.reset_index(drop=True)
            if not accel_df.empty:
                topics[f"sensor_accel_{instance}"] = accel_df.reset_index(drop=True)
                if instance == 0:
                    topics["sensor_accel"] = accel_df.reset_index(drop=True)

        if bat_rows:
            bat_df = pd.DataFrame(bat_rows).dropna(subset=["voltage_v", "current_a"], how="all")
            if not bat_df.empty:
                # Derive a fractional "remaining" estimate if a rated capacity
                # parameter is present (BATT_CAPACITY, mAh); otherwise the
                # column is omitted and the battery analyser's capacity-fade
                # check gracefully skips, matching PX4 behaviour when the
                # rated capacity isn't available in the log either.
                rated_mah = params.get("BATT_CAPACITY")
                if rated_mah and rated_mah > 0 and "current_consumed_mah" in bat_df.columns:
                    consumed = bat_df["current_consumed_mah"].fillna(0)
                    bat_df["remaining"] = (1.0 - consumed / rated_mah).clip(lower=0.0, upper=1.0)
                    bat_df["capacity"] = rated_mah
                topics["battery_status"] = bat_df.reset_index(drop=True)

        if gps_rows:
            gps_df = pd.DataFrame(gps_rows).dropna(subset=["lat", "lon"], how="all")
            if not gps_df.empty:
                # ArduPilot's GPS message already logs Lat/Lng as degrees
                # (float); PX4's vehicle_gps_position stores lat/lon as
                # int32 degrees*1e7 and alt in mm. Convert to match so the
                # orchestrator's existing GPS-path/weather extraction code
                # (which divides by 1e7 / 1000.0) works unmodified.
                gps_df["lat"] = (gps_df["lat"] * 1e7).round().astype("Int64")
                gps_df["lon"] = (gps_df["lon"] * 1e7).round().astype("Int64")
                if "alt" in gps_df.columns:
                    gps_df["alt"] = (gps_df["alt"] * 1000.0).round()
                # ArduPilot has no GPS jamming/spoofing indicator equivalent —
                # jamming_indicator/spoofing_state are intentionally omitted;
                # the GPS analyser skips those specific checks when absent.
                topics["vehicle_gps_position"] = gps_df.reset_index(drop=True)

        for instance, rows in esc_rows.items():
            esc_df = pd.DataFrame(rows).dropna(how="all", subset=["rpm", "current", "temperature"])
            if esc_df.empty:
                continue
            esc_df = esc_df.rename(columns={
                "rpm": f"esc_{instance}_rpm",
                "current": f"esc_{instance}_current",
                "temperature": f"esc_{instance}_temperature",
            })
            if "esc_status" not in topics:
                topics["esc_status"] = esc_df[["timestamp"]].copy()
            topics["esc_status"] = topics["esc_status"].merge(
                esc_df, on="timestamp", how="outer"
            ).sort_values("timestamp").reset_index(drop=True)

        duration_s = 0.0
        if first_ts_us is not None and last_ts_us is not None:
            duration_s = (last_ts_us - first_ts_us) / 1e6

        metadata = FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=firmware_version,
            vehicle_type=_vehicle_type_from_firmware_string(firmware_version),
            arm_count=arm_events,
            flight_modes_used=sorted(set(mode_changes)),
            available_topics=sorted(topics.keys()),
        )

        logger.info(
            f"Parsed ArduPilot log: {len(topics)} topics, {len(params)} params, "
            f"duration={duration_s:.1f}s"
        )
        return topics, params, metadata


def _is_numeric(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


_FIRMWARE_TO_VEHICLE_TYPE = {
    "ArduCopter": "Copter",
    "ArduPlane": "Plane",
    "ArduRover": "Rover",
    "ArduSub": "Sub",
    "Blimp": "Blimp",
    "AntennaTracker": "AntennaTracker",
}


def _vehicle_type_from_firmware_string(firmware_version: Optional[str]) -> Optional[str]:
    """ArduPilot's startup MSG line (e.g. "ArduCopter V4.3.5 (02ff7ea3)") is the
    only place the vehicle type is recorded in a dataflash log — there's no
    separate vehicle-type field to read."""
    if not firmware_version:
        return None
    for prefix, vehicle_type in _FIRMWARE_TO_VEHICLE_TYPE.items():
        if prefix in firmware_version:
            return vehicle_type
    return None
