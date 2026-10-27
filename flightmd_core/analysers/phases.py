"""
Armed and in-air windows for a log.

Built from `vehicle_status.arming_state` (2 = armed, PX4 numbering; the
parsers map ArduPilot and MAVLink onto it) and, when present,
`vehicle_land_detected.landed`. Logs with neither fall back to the whole
log, and `known` is False so analysers can say so or apply their own
cheaper guards (e.g. skipping GPS acquisition at the start).

Windows are (start_us, end_us) on the topics' log-relative clock. A window
still open at the end of the data runs to +inf, and one already open at the
first status row starts at -inf, so samples logged a few ms before the
first status message aren't dropped.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

ARMED = 2

WHOLE_LOG = [(-math.inf, math.inf)]


@dataclass
class FlightPhases:
    armed: list[tuple[float, float]]
    in_air: list[tuple[float, float]]
    source: str      # "vehicle_status", "vehicle_status+land_detected" or "whole_log"

    @property
    def known(self) -> bool:
        return self.source != "whole_log"

    def mask(self, ts_us, phase: str = "in_air") -> np.ndarray:
        windows = self.in_air if phase == "in_air" else self.armed
        ts = np.asarray(ts_us, dtype=float)
        m = np.zeros(ts.shape, dtype=bool)
        for a, b in windows:
            m |= (ts >= a) & (ts <= b)
        return m

    def describe(self, phase: str = "in_air") -> str:
        if not self.known:
            return "whole log (no arming data)"
        return "in flight" if phase == "in_air" else "while armed"


def _first(topics: dict, *names):
    for n in names:
        df = topics.get(n)
        if df is not None and len(df) and "timestamp" in df.columns:
            return df
    return None


def _windows(ts: np.ndarray, on: np.ndarray) -> list[tuple[float, float]]:
    out = []
    start = None
    for i, (t, v) in enumerate(zip(ts, on)):
        if v and start is None:
            start = -math.inf if i == 0 else float(t)
        elif not v and start is not None:
            out.append((start, float(t)))
            start = None
    if start is not None:
        out.append((start, math.inf))
    return out


def _intersect(a, b):
    out = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if lo < hi:
                out.append((lo, hi))
    return out


def flight_phases(topics: dict[str, pd.DataFrame]) -> FlightPhases:
    status = _first(topics, "vehicle_status", "vehicle_status_0")
    armed = []
    if status is not None and "arming_state" in status.columns:
        st = status[["timestamp", "arming_state"]].dropna().sort_values("timestamp")
        armed = _windows(st["timestamp"].to_numpy(float), (st["arming_state"] == ARMED).to_numpy())

    # never armed (bench log, or arming info that didn't survive parsing):
    # gating on it would blank every module, so treat it as unknown
    if not armed:
        return FlightPhases(WHOLE_LOG, WHOLE_LOG, "whole_log")

    land = _first(topics, "vehicle_land_detected", "vehicle_land_detected_0")
    if land is None or "landed" not in land.columns:
        return FlightPhases(armed, armed, "vehicle_status")

    ld = land[["timestamp", "landed"]].dropna().sort_values("timestamp")
    flying = _windows(ld["timestamp"].to_numpy(float), ~ld["landed"].astype(bool).to_numpy())
    in_air = _intersect(armed, flying)
    if not in_air:
        # armed but the land detector never cleared: rovers, boats, or a
        # detector that isn't logged properly. Armed is the best we have.
        in_air = armed
    return FlightPhases(armed, in_air, "vehicle_status+land_detected")
