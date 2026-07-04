"""
Shared pytest fixtures for FlightMD test suite.
"""

import os
import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

from httpx import AsyncClient
from flightmd_core.models.findings import (
    Finding, Category, Severity, AnalyserResult
)
from flightmd_core.models.metadata import FlightMetadata


# ── Fixture: minimal FlightMetadata ─────────────────────────────────────────

@pytest.fixture
def sample_metadata() -> FlightMetadata:
    return FlightMetadata(
        duration_seconds=300.0,
        firmware_version="v1.14.0",
        hardware_id="px4_fmu-v6x",
        airframe_id=4001,
        arm_count=1,
        flight_modes_used=["Position Control", "Auto Mission"],
        max_altitude_m=50.0,
        max_speed_ms=8.5,
        available_topics=[
            "vehicle_angular_velocity",
            "sensor_accel_0",
            "estimator_status",
            "battery_status",
            "vehicle_gps_position",
        ],
    )


# ── Fixture: clean angular velocity DataFrame (no oscillation) ───────────────

@pytest.fixture
def clean_angular_velocity() -> pd.DataFrame:
    n = 5000
    t = np.linspace(0, 20, n)
    ts = (t * 1e6).astype(int)
    noise = np.random.default_rng(42).normal(0, 0.01, n)
    return pd.DataFrame({
        "timestamp":  ts,
        "rollspeed":  noise,
        "pitchspeed": noise * 0.8,
        "yawspeed":   noise * 0.5,
    })


# ── Fixture: oscillating angular velocity DataFrame ──────────────────────────

@pytest.fixture
def oscillating_angular_velocity() -> pd.DataFrame:
    n = 5000
    t = np.linspace(0, 20, n)
    ts = (t * 1e6).astype(int)
    rng = np.random.default_rng(42)
    oscillation = 0.8 * np.sin(2 * np.pi * 6.0 * t)  # 6 Hz dominant
    noise       = rng.normal(0, 0.02, n)
    return pd.DataFrame({
        "timestamp":  ts,
        "rollspeed":  oscillation + noise,
        "pitchspeed": noise,
        "yawspeed":   noise * 0.3,
    })


# ── Fixture: high-vibration IMU ──────────────────────────────────────────────

@pytest.fixture
def high_vibration_accel() -> pd.DataFrame:
    n = 2000
    t = np.linspace(0, 10, n)
    rng = np.random.default_rng(42)
    # RMS ~70 m/s² — CRITICAL threshold
    signal = rng.normal(0, 70 / np.sqrt(2), n)
    return pd.DataFrame({
        "timestamp": (t * 1e6).astype(int),
        "x": signal,
        "y": signal * 0.9,
        "z": signal * 0.7,
    })


# ── Fixture: healthy battery DataFrame ──────────────────────────────────────

@pytest.fixture
def healthy_battery() -> pd.DataFrame:
    n = 3000
    t = np.linspace(0, 300, n)
    # 4S, idle ~16.8V, small sag under load
    sag = np.clip(np.random.default_rng(42).normal(0, 0.1, n), -0.2, 0.2)
    return pd.DataFrame({
        "timestamp": (t * 1e6).astype(int),
        "voltage_v": 16.8 - t / 300 * 1.5 + sag,
        "current_a": np.where(t < 5, 2.0, 20.0 + sag * 2),
        "remaining": np.clip(1.0 - t / 300 * 0.8, 0.1, 1.0),
    })


# ── Fixture: healthy GPS DataFrame ──────────────────────────────────────────

@pytest.fixture
def healthy_gps() -> pd.DataFrame:
    n = 1000
    t = np.linspace(0, 300, n)
    return pd.DataFrame({
        "timestamp":      (t * 1e6).astype(int),
        "fix_type":       np.full(n, 3),
        "satellites_used": np.full(n, 14),
        "hdop":           np.full(n, 0.9),
        "jamming_indicator": np.zeros(n, dtype=int),
        "spoofing_state": np.full(n, 2),
    })


# ── FastAPI test client ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_client():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    from api.main import app
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


# ── Minimal ULog magic bytes file ────────────────────────────────────────────

@pytest.fixture
def ulg_magic_bytes() -> bytes:
    """Returns minimal valid ULog header magic bytes."""
    return b"\x55\x4C\x6F\x67\x01\x00\x00\x00"
