"""
ULogParser — pyulog wrapper that returns typed DataFrames and metadata.

Handles PX4 ULog format (.ulg files). Extracts:
  - topics: Dict[str, pd.DataFrame] — sensor and estimator data
  - params: Dict[str, float]        — logged parameters
  - metadata: FlightMetadata        — extracted flight info
"""

import os
import logging
from typing import Optional
import numpy as np
import pandas as pd

try:
    from pyulog import ULog
except ImportError as e:
    raise ImportError(
        "pyulog is required. Install it with: pip install pyulog"
    ) from e

from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)

# Known ULog topic name aliases across PX4 versions
TOPIC_ALIASES: dict[str, list[str]] = {
    "vehicle_angular_velocity": ["vehicle_angular_velocity", "angular_velocity"],
    "sensor_accel": ["sensor_accel_0", "sensor_accel_1", "sensor_accel_2", "sensor_accel"],
    "estimator_status": ["estimator_status_0", "estimator_status"],
    "battery_status": ["battery_status_0", "battery_status"],
    "vehicle_gps_position": ["vehicle_gps_position_0", "vehicle_gps_position"],
    "esc_status": ["esc_status_0", "esc_status"],
    "estimator_innovation_test_ratios": [
        "estimator_innovation_test_ratios_0",
        "estimator_innovation_test_ratios",
    ],
    "estimator_sensor_bias": ["estimator_sensor_bias_0", "estimator_sensor_bias"],
    "sensor_gnss_relative": ["sensor_gnss_relative_0", "sensor_gnss_relative"],
}

# Every raw topic name any analyser or metadata field reads (base names —
# pyulog returns every multi-instance under the same base name, and our own
# _extract_topics adds the _0/_1/_2 suffixes afterwards). Passed to pyulog's
# message_name_filter_list by default so it builds DataFrames for fewer
# topics (lower memory, slightly less post-processing).
#
# NOTE: this does NOT fix pathologically slow parsing on very
# message-dense logs. Profiled on a real 303MB/67-topic/~2.3M-message
# quadrotor log: message_name_filter_list still took ~190s even
# restricted to a single topic. pyulog's _read_file_data scans every
# message's header sequentially regardless of the filter (it has to,
# to know each message's type/size before deciding to keep or skip it)
# — confirmed via cProfile: 218M BufferedReader.read() calls and 105M
# packet-corruption checks, both independent of the topic filter. This
# is an upstream pyulog performance ceiling (already on the latest
# release, 1.2.3), not something this filter list can address. Kept
# anyway for the memory/DataFrame-construction benefit on the other
# 49/50 real logs tested, where it's a straightforward win.
REQUIRED_ULOG_TOPICS: list[str] = [
    "vehicle_angular_velocity",
    "angular_velocity",
    "sensor_accel",
    "estimator_status",
    "estimator_innovation_test_ratios",
    "estimator_sensor_bias",
    "battery_status",
    "vehicle_gps_position",
    "sensor_gnss_relative",
    "esc_status",
    "vehicle_status",
    "vehicle_local_position",
]

# Flight mode mapping (PX4 nav_state values)
FLIGHT_MODE_NAMES: dict[int, str] = {
    0:  "Manual",
    1:  "Altitude Control",
    2:  "Position Control",
    3:  "Auto Mission",
    4:  "Auto Loiter",
    5:  "Auto Return",
    6:  "Acro",
    8:  "Stabilized",
    9:  "Rattitude",
    10: "Auto Takeoff",
    11: "Auto Land",
    12: "Auto Follow Target",
    13: "Auto Precision Land",
    14: "Orbit",
    17: "VTOL Transition",
    19: "Offboard",
}


class ULogParser:
    """
    Parses a PX4 ULog file and returns structured data.
    """

    def parse(
        self,
        ulog_path: str,
        load_topic_names: Optional[list[str]] = REQUIRED_ULOG_TOPICS,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]:
        """
        Parse a .ulg file.

        Args:
            ulog_path: absolute path to the .ulg file
            load_topic_names: topics to load (default: only what FlightMD's
                analysers/metadata actually consume — pass None to load
                every topic in the file instead, e.g. for debugging)

        Returns:
            (topics, params, metadata)
            topics:   canonical topic name → DataFrame
            params:   parameter name → float value
            metadata: FlightMetadata instance
        """
        if not os.path.exists(ulog_path):
            raise FileNotFoundError(f"ULog file not found: {ulog_path}")

        logger.info(f"Parsing ULog: {ulog_path}")

        ulog = ULog(ulog_path, load_topic_names)

        topics  = self._extract_topics(ulog)
        params  = self._extract_params(ulog)
        metadata = self._extract_metadata(ulog, topics)

        logger.info(
            f"Parsed {len(topics)} topics, {len(params)} params, "
            f"duration={metadata.duration_seconds:.1f}s"
        )
        return topics, params, metadata

    # ── topic extraction ─────────────────────────────────────────────────────

    def _extract_topics(self, ulog: ULog) -> dict[str, pd.DataFrame]:
        """
        Convert all ULog data objects to DataFrames.
        Apply canonical naming so analysers use consistent keys.
        """
        raw: dict[str, pd.DataFrame] = {}

        for d in ulog.data_list:
            topic_name = d.name
            if d.multi_id > 0:
                key = f"{topic_name}_{d.multi_id}"
            else:
                key = topic_name

            try:
                df = pd.DataFrame.from_dict(d.data)
                # Ensure timestamp column always present
                if "timestamp" not in df.columns and len(df) > 0:
                    df.insert(0, "timestamp", range(len(df)))
                raw[key] = df
                # Also store un-suffixed key for the primary instance
                if d.multi_id == 0 and topic_name not in raw:
                    raw[topic_name] = df
            except Exception as e:
                logger.warning(f"Failed to convert topic {key} to DataFrame: {e}")

        # Apply canonical aliases
        canonical: dict[str, pd.DataFrame] = dict(raw)
        for canonical_name, aliases in TOPIC_ALIASES.items():
            if canonical_name in canonical:
                continue
            for alias in aliases:
                if alias in raw:
                    canonical[canonical_name] = raw[alias]
                    break

        logger.debug(f"Available topics: {sorted(canonical.keys())}")
        return canonical

    # ── parameter extraction ─────────────────────────────────────────────────

    def _extract_params(self, ulog: ULog) -> dict[str, float]:
        """Extract initial parameter set as float dict."""
        params: dict[str, float] = {}
        for k, v in ulog.initial_parameters.items():
            try:
                params[k] = float(v)
            except (TypeError, ValueError):
                pass
        return params

    # ── metadata extraction ──────────────────────────────────────────────────

    def _extract_metadata(
        self,
        ulog: ULog,
        topics: dict[str, pd.DataFrame],
    ) -> FlightMetadata:
        duration_us = ulog.last_timestamp - ulog.start_timestamp
        duration_s  = duration_us / 1e6

        # Firmware / hardware — msg_info_dict values come straight from the
        # log's own info section, which real (non-simulated) firmware can
        # encode as an int rather than a string (e.g. ver_sw_release as a
        # raw packed version number) — every field pulled from it needs an
        # explicit str() cast or a real-world log fails FlightMetadata
        # validation outright. Confirmed across 13/13 real public PX4 logs
        # (all vehicle types) before this fix.
        def _as_str(value):
            return str(value) if value is not None else None

        fw_version  = _as_str(ulog.msg_info_dict.get("ver_sw", None))
        hw_id       = _as_str(ulog.msg_info_dict.get("ver_hw", None))
        px4_version = _as_str(ulog.msg_info_dict.get("ver_sw_release", None))

        # Airframe
        airframe_id   = None
        airframe_name = None
        vehicle_type  = None
        try:
            airframe_id   = int(ulog.initial_parameters.get("SYS_AUTOSTART", 0))
            vehicle_type  = _as_str(ulog.msg_info_dict.get("sys_name", None))
        except Exception:
            pass

        # Log start UTC
        log_start_utc = None
        try:
            ts_utc = ulog.msg_info_dict.get("time_ref_utc")
            if ts_utc:
                log_start_utc = str(ts_utc)
        except Exception:
            pass

        # Arm count — from vehicle_status topic
        arm_count = self._count_arms(topics)

        # Flight modes
        flight_modes = self._extract_flight_modes(topics)

        # Altitude, speed, distance
        max_altitude  = self._max_altitude(topics)
        max_speed     = self._max_speed(topics)
        total_dist    = self._total_distance(topics)

        return FlightMetadata(
            duration_seconds=round(duration_s, 2),
            firmware_version=fw_version,
            hardware_id=hw_id,
            airframe_id=airframe_id,
            airframe_name=airframe_name,
            vehicle_type=vehicle_type,
            log_start_utc=log_start_utc,
            arm_count=arm_count,
            flight_modes_used=flight_modes,
            max_altitude_m=max_altitude,
            max_speed_ms=max_speed,
            total_distance_m=total_dist,
            px4_version=px4_version,
            available_topics=sorted(topics.keys()),
        )

    def _count_arms(self, topics: dict[str, pd.DataFrame]) -> int:
        """Count number of arm events from vehicle_status."""
        for name in ["vehicle_status", "vehicle_status_0"]:
            if name in topics:
                df = topics[name]
                if "arming_state" in df.columns:
                    # arming_state == 2 means ARMED in PX4
                    armed = (df["arming_state"] == 2).values
                    transitions = np.diff(armed.astype(int))
                    return int((transitions == 1).sum())
        return 0

    def _extract_flight_modes(self, topics: dict[str, pd.DataFrame]) -> list[str]:
        """Extract unique flight modes used during the flight."""
        modes: set[str] = set()
        for name in ["vehicle_status", "vehicle_status_0"]:
            if name in topics:
                df = topics[name]
                col = next((c for c in ["nav_state", "nav_state_timestamp"] if c in df.columns), None)
                if col:
                    for mode_id in df[col].dropna().unique():
                        label = FLIGHT_MODE_NAMES.get(int(mode_id), f"Mode {int(mode_id)}")
                        modes.add(label)
        return sorted(modes)

    def _max_altitude(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        """Return max altitude in metres from local position."""
        for name in ["vehicle_local_position", "vehicle_local_position_0"]:
            if name in topics:
                df = topics[name]
                col = next((c for c in ["z", "alt"] if c in df.columns), None)
                if col:
                    vals = df[col].dropna().values
                    if len(vals) > 0:
                        # PX4 local Z is positive down — negate for altitude
                        if col == "z":
                            return round(float(-vals.min()), 1)
                        return round(float(vals.max()), 1)
        return None

    def _max_speed(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        """Return max groundspeed in m/s."""
        for name in ["vehicle_local_position", "vehicle_local_position_0"]:
            if name in topics:
                df = topics[name]
                vx = df.get("vx", pd.Series(dtype=float)).values
                vy = df.get("vy", pd.Series(dtype=float)).values
                if len(vx) > 0 and len(vy) > 0:
                    speed = np.sqrt(vx**2 + vy**2)
                    return round(float(speed.max()), 2)
        return None

    def _total_distance(self, topics: dict[str, pd.DataFrame]) -> Optional[float]:
        """Estimate total horizontal distance flown in metres."""
        for name in ["vehicle_local_position", "vehicle_local_position_0"]:
            if name in topics:
                df = topics[name]
                if "x" in df.columns and "y" in df.columns:
                    x = df["x"].dropna().values
                    y = df["y"].dropna().values
                    if len(x) > 1 and len(y) > 1:
                        dist = float(np.sum(np.sqrt(np.diff(x)**2 + np.diff(y)**2)))
                        return round(dist, 1)
        return None
