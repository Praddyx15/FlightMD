"""
PX4 ULog (.ulg) parser on top of pyulog.

parse() returns (topics, params, metadata). Topic timestamps are shifted so the log
starts at 0 (microseconds), the primary instance of a multi-instance topic sits under
the bare name and the rest under <name>_1, <name>_2.
"""

import logging
import os
import re
from typing import Callable, Optional

import numpy as np
import pandas as pd

try:
    from pyulog import ULog
except ImportError as e:
    raise ImportError(
        "pyulog is required. Install it with: pip install pyulog"
    ) from e

from flightmd_core.models.metadata import MIN_EPOCH_US, FlightMetadata, utc_iso
from flightmd_core.services.airframes import px4_airframe

logger = logging.getLogger(__name__)

# other names the same data has had across PX4 versions
TOPIC_ALIASES: dict[str, list[str]] = {
    "vehicle_angular_velocity": ["angular_velocity"],
    "vehicle_gps_position": ["sensor_gps"],
}

# Only these get turned into DataFrames. It saves memory but not time: pyulog still
# reads every message header (a 300 MB log takes minutes either way).
REQUIRED_ULOG_TOPICS: list[str] = [
    "vehicle_angular_velocity",
    "angular_velocity",
    "sensor_accel",
    "estimator_status",
    "estimator_innovation_test_ratios",
    "estimator_sensor_bias",
    "estimator_selector_status",
    "battery_status",
    "vehicle_gps_position",
    "sensor_gps",
    "sensor_gnss_relative",
    "esc_status",
    "vehicle_status",
    "vehicle_land_detected",
    "vehicle_local_position",
    "vehicle_imu_status",
    "system_power",
]

# vehicle_status.vehicle_type (VEHICLE_TYPE_* in vehicle_status.msg)
VEHICLE_TYPES = {1: "Copter", 2: "Plane", 3: "Rover", 4: "Airship"}

PROGRESS_EVERY = 1 << 16  # reads; pyulog does two per message

# vehicle_status.nav_state, from PX4's msg/vehicle_status.msg.
# 6-9 and 16 changed meaning over the years: 7/8/9/16 are gone since ~1.13,
# 6 is POSITION_SLOW from 1.15 (was AUTO_RCRECOVER long ago).
FLIGHT_MODE_NAMES: dict[int, str] = {
    0:  "Manual",
    1:  "Altitude Control",
    2:  "Position Control",
    3:  "Auto Mission",
    4:  "Auto Loiter",
    5:  "Auto Return",
    6:  "Position Slow",
    7:  "Auto Return to Groundstation",
    8:  "Auto Land (Engine Fail)",
    9:  "Auto Land (GPS Fail)",
    10: "Acro",
    12: "Descend",
    13: "Termination",
    14: "Offboard",
    15: "Stabilized",
    16: "Rattitude",
    17: "Auto Takeoff",
    18: "Auto Land",
    19: "Auto Follow Target",
    20: "Auto Precision Land",
    21: "Orbit",
    22: "Auto VTOL Takeoff",
}

_ESC_COL = re.compile(r"esc\[(\d+)\]\.")


class _Progress:
    """File wrapper for pyulog that reports how far through the file it's read.
    pyulog has no progress hook, but it takes any object with read/seek/tell."""

    def __init__(self, f, size: int, report: Callable[[float], None]):
        self._f = f
        self._size = max(size, 1)
        self._report = report
        self._reads = 0

    def read(self, n=-1):
        self._reads += 1
        if self._reads % PROGRESS_EVERY == 0:
            self._report(min(self._f.tell() / self._size, 1.0))
        return self._f.read(n)

    def __getattr__(self, name):
        return getattr(self._f, name)


class ULogParser:

    def parse(
        self,
        ulog_path: str,
        load_topic_names: Optional[list[str]] = REQUIRED_ULOG_TOPICS,
        progress: Optional[Callable[[float], None]] = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        """load_topic_names=None loads every topic in the file (handy for debugging).
        progress, if given, is called now and then with the fraction read (0-1)."""
        if not os.path.exists(ulog_path):
            raise FileNotFoundError(f"ULog file not found: {ulog_path}")

        logger.info(f"Parsing ULog: {ulog_path}")
        if progress is None:
            ulog = ULog(ulog_path, load_topic_names)
        else:
            # pyulog closes it when it finishes; this is for when it raises
            f = open(ulog_path, "rb")
            try:
                ulog = ULog(_Progress(f, os.path.getsize(ulog_path), progress), load_topic_names)
            finally:
                f.close()

        topics = self._extract_topics(ulog)
        params = self._extract_params(ulog)
        metadata = self._extract_metadata(ulog, topics)
        metadata.parse_warnings = self._warnings(ulog)

        logger.info(
            f"Parsed {len(topics)} topics, {len(params)} params, "
            f"duration={metadata.duration_seconds:.1f}s"
        )
        return topics, params, metadata

    def _extract_topics(self, ulog: ULog) -> dict[str, pd.DataFrame]:
        start = int(ulog.start_timestamp)
        topics: dict[str, pd.DataFrame] = {}

        for d in ulog.data_list:
            key = d.name if d.multi_id == 0 else f"{d.name}_{d.multi_id}"
            df = pd.DataFrame.from_dict(d.data)
            if df.empty or "timestamp" not in df.columns:
                continue
            # pyulog gives uint64; go signed before subtracting
            for col in ("timestamp", "timestamp_sample"):
                if col in df.columns:
                    df[col] = df[col].astype("int64") - start
            topics[key] = df

        for name, alts in TOPIC_ALIASES.items():
            if name not in topics:
                src = next((a for a in alts if a in topics), None)
                if src:
                    topics[name] = topics[src]

        _use_primary_ekf(topics)

        for key, df in topics.items():
            if key.startswith(("vehicle_gps_position", "sensor_gps")):
                _normalise_gps(df)
            elif key.startswith("esc_status"):
                topics[key] = _trim_esc(df)

        logger.debug(f"Available topics: {sorted(topics.keys())}")
        return topics

    def _extract_params(self, ulog: ULog) -> dict[str, float]:
        params: dict[str, float] = {}
        for k, v in ulog.initial_parameters.items():
            try:
                params[k] = float(v)
            except (TypeError, ValueError):
                pass
        return params

    def _extract_metadata(
        self,
        ulog: ULog,
        topics: dict[str, pd.DataFrame],
    ) -> FlightMetadata:
        duration_s = (ulog.last_timestamp - ulog.start_timestamp) / 1e6

        # Real firmware writes some of these info fields as ints (ver_sw_release is a
        # packed number), so everything goes through str().
        def as_str(value):
            return str(value) if value is not None else None

        info = ulog.msg_info_dict
        airframe_id = ulog.initial_parameters.get("SYS_AUTOSTART")
        airframe_name, _ = px4_airframe(airframe_id)

        board = as_str(info.get("ver_hw"))
        if board and info.get("ver_hw_subtype"):
            board = f"{board} ({info['ver_hw_subtype']})"

        return FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=as_str(info.get("ver_sw")),
            hardware_id=board,
            airframe_id=int(airframe_id) if airframe_id is not None else None,
            airframe_name=airframe_name,
            # sys_name is just "PX4"; vehicle_status says what actually flew
            vehicle_type=_vehicle_type(topics) or as_str(info.get("sys_name")),
            # time_ref_utc in the info section is the local UTC offset, not a time
            log_start_utc=_log_start_utc(topics),
            arm_count=self._count_arms(topics),
            flight_modes_used=self._extract_flight_modes(topics),
            max_altitude_m=self._max_altitude(topics),
            max_speed_ms=self._max_speed(topics),
            total_distance_m=self._total_distance(topics),
            px4_version=_px4_release(info.get("ver_sw_release")),
            available_topics=sorted(topics.keys()),
        )

    def _warnings(self, ulog) -> list[str]:
        out = []
        if getattr(ulog, "file_corruption", False):
            out.append("The log file is corrupted in places; pyulog skipped the damaged parts.")
        drops = getattr(ulog, "dropouts", None) or []
        if drops:
            lost_s = sum(d.duration for d in drops) / 1000  # pyulog gives ms
            out.append(f"The logger dropped data {len(drops)} times ({lost_s:.1f} s in total).")
        return out

    def _count_arms(self, topics: dict[str, pd.DataFrame]) -> int:
        df = topics.get("vehicle_status")
        if df is None or "arming_state" not in df.columns:
            return 0
        armed = (df["arming_state"] == 2).to_numpy(dtype=int)  # 2 = ARMED
        return int((np.diff(armed) == 1).sum())

    def _extract_flight_modes(self, topics: dict[str, pd.DataFrame]) -> list[str]:
        df = topics.get("vehicle_status")
        if df is None or "nav_state" not in df.columns:
            return []
        modes = {
            FLIGHT_MODE_NAMES.get(int(m), f"Mode {int(m)}")
            for m in df["nav_state"].dropna().unique()
        }
        return sorted(modes)

    def _max_altitude(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        df = topics.get("vehicle_local_position")
        if df is None:
            return None
        col = next((c for c in ["z", "alt"] if c in df.columns), None)
        if not col:
            return None
        vals = df[col].dropna().to_numpy()
        if len(vals) == 0:
            return None
        # local z is NED, positive down
        if col == "z":
            return round(float(-vals.min()), 1)
        return round(float(vals.max()), 1)

    def _max_speed(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        df = topics.get("vehicle_local_position")
        if df is None or "vx" not in df.columns or "vy" not in df.columns:
            return None
        speed = np.hypot(df["vx"].to_numpy(dtype=float), df["vy"].to_numpy(dtype=float))
        speed = speed[np.isfinite(speed)]
        return round(float(speed.max()), 2) if speed.size else None

    def _total_distance(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        df = topics.get("vehicle_local_position")
        if df is None or "x" not in df.columns or "y" not in df.columns:
            return None
        xy = df[["x", "y"]].dropna().to_numpy(dtype=float)
        if len(xy) < 2:
            return None
        return round(float(np.hypot(*np.diff(xy, axis=0).T).sum()), 1)


def _vehicle_type(topics: dict[str, pd.DataFrame]) -> Optional[str]:
    df = topics.get("vehicle_status")
    if df is None or df.empty:
        return None
    if "is_vtol" in df.columns and df["is_vtol"].astype(bool).any():
        return "VTOL"
    if "vehicle_type" in df.columns:
        kinds = df["vehicle_type"].dropna()
        kinds = kinds[kinds > 0]
        if not kinds.empty:
            return VEHICLE_TYPES.get(int(kinds.mode().iloc[0]))
    # before ~1.14 there was only is_rotary_wing
    if "is_rotary_wing" in df.columns:
        return "Copter" if df["is_rotary_wing"].astype(bool).mode().iloc[0] else "Plane"
    return None


def _use_primary_ekf(topics: dict[str, pd.DataFrame]) -> None:
    """With multi-EKF the primary isn't always instance 0; swap it onto the bare name."""
    sel = topics.get("estimator_selector_status")
    if sel is None or "primary_instance" not in sel.columns or sel.empty:
        return
    # the one that was primary for most of the log
    primary = int(sel["primary_instance"].mode().iloc[0])
    if primary == 0:
        return
    # assumes multi_id == EKF instance, which is how PX4 advertises them
    for name in [k for k in topics if k.startswith("estimator_") and k != "estimator_selector_status"]:
        other = f"{name}_{primary}"
        if other in topics:
            topics[name], topics[other] = topics[other], topics[name]


def _normalise_gps(df: pd.DataFrame) -> None:
    """PX4 1.15 renamed lat/lon/alt to float latitude_deg etc.; put back degE7 / mm."""
    if "lat" not in df.columns and "latitude_deg" in df.columns:
        df["lat"] = (df["latitude_deg"].fillna(0) * 1e7).round().astype("int64")
        df["lon"] = (df["longitude_deg"].fillna(0) * 1e7).round().astype("int64")
    if "alt" not in df.columns and "altitude_msl_m" in df.columns:
        df["alt"] = (df["altitude_msl_m"].fillna(0) * 1000).round().astype("int64")


def _trim_esc(df: pd.DataFrame) -> pd.DataFrame:
    """esc_status always carries 8 slots; keep only the ones that are real ESCs."""
    slots = {c: int(m.group(1)) for c in df.columns if (m := _ESC_COL.match(c))}
    if not slots:
        return df
    n = int(df["esc_count"].max()) if "esc_count" in df.columns else 0
    if n <= 0:
        # no count logged: up to the last slot that ever reports anyting
        live = {i for c, i in slots.items() if df[c].fillna(0).ne(0).any()}
        n = max(live) + 1 if live else 0
    df = df.drop(columns=[c for c, i in slots.items() if i >= n])
    df["esc_count"] = n
    return df


def _px4_release(value) -> Optional[str]:
    """ver_sw_release is packed 0xAABBCCTT: major, minor, patch, type (255 = release)."""
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    major, minor, patch, kind = (n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF
    tag = "" if kind == 255 else "-rc" if kind >= 192 else "-beta" if kind >= 128 else "-alpha" if kind >= 64 else "-dev"
    return f"v{major}.{minor}.{patch}{tag}"


def _log_start_utc(topics: dict[str, pd.DataFrame]) -> Optional[str]:
    """GPS time_utc_usec minus the (log-relative) sample time of the same row."""
    for name in ("vehicle_gps_position", "sensor_gps"):
        df = topics.get(name)
        if df is None or "time_utc_usec" not in df.columns:
            continue
        ok = df[df["time_utc_usec"].astype("float64") > MIN_EPOCH_US]
        if not ok.empty:
            r = ok.iloc[0]
            return utc_iso(float(r["time_utc_usec"]) - float(r["timestamp"]))
    return None
