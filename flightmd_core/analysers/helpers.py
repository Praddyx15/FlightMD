"""Small helpers shared by the analysers and the report builder."""

import math
from typing import Optional

import numpy as np
import pandas as pd

MAX_CHART_POINTS = 500


def find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def find_runs(mask) -> list[tuple[int, int]]:
    """(start, end) index pairs of True runs, end exclusive."""
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return []
    edges = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def run_seconds(ts_us: np.ndarray, start: int, end: int) -> float:
    """Duration of samples [start, end) in seconds. The run is taken to last
    until the next sample arrives, so a single sample still has a length."""
    if end < len(ts_us):
        return float(ts_us[end] - ts_us[start]) / 1e6
    if len(ts_us) > 1:
        dt = float(np.median(np.diff(ts_us)))
        return float(ts_us[end - 1] - ts_us[start] + dt) / 1e6
    return 0.0


def sample_rate_hz(ts_us, default: float) -> float:
    ts = np.asarray(ts_us, dtype=float)
    if ts.size < 2:
        return default
    dt = float(np.median(np.diff(ts)))
    return 1e6 / dt if dt > 0 else default


def to_list(arr) -> list:
    """numpy array -> JSON-safe list, NaN/inf -> None."""
    a = np.asarray(arr, dtype=float)
    return [float(v) if math.isfinite(v) else None for v in a.tolist()]


def downsample(ts_us, *series, n: int = MAX_CHART_POINTS) -> list[list]:
    """Stride-downsample a timestamp array (µs) and any parallel series to at
    most n points. Returns [timestamps_ms, series1, ...] as JSON-safe lists."""
    ts = np.asarray(ts_us, dtype=float)
    step = max(1, math.ceil(len(ts) / n)) if len(ts) else 1
    out = [to_list(ts[::step] / 1e3)]
    for s in series:
        out.append(to_list(np.asarray(s, dtype=float)[::step]))
    return out


def clean(obj):
    """Recursively make a value JSON-safe: numpy -> python, NaN/inf -> None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def when(start_us=None, end_us=None) -> dict:
    """Finding kwargs for a log-relative time window given in µs."""
    out = {}
    if start_us is not None and math.isfinite(start_us):
        out["timestamp_start_ms"] = int(start_us / 1e3)
        out["t_start_s"] = round(start_us / 1e6, 3)
    if end_us is not None and math.isfinite(end_us):
        out["timestamp_end_ms"] = int(end_us / 1e3)
        out["t_end_s"] = round(end_us / 1e6, 3)
    return out


def confidence(margin: float, duration_s: Optional[float] = None, quality: float = 1.0) -> float:
    """Confidence from how far past the threshold a metric went (margin, as a
    fraction of the threshold: 0 = just over it, 1 = twice it), how long it
    lasted, and how good the data was (0-1, e.g. share of expected samples).

    Just over the line, briefly, on patchy data -> low; well over, for
    seconds, on clean data -> high.
    """
    m = 0.5 + 0.5 * min(1.0, max(0.0, margin))
    d = 1.0 if duration_s is None else 0.4 + 0.6 * min(1.0, max(0.0, duration_s) / 2.0)
    q = min(1.0, max(0.0, quality))
    return round(m * d * q, 3)
