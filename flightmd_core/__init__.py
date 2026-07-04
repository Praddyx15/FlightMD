"""
flightmd_core — multi-format drone flight log analysis engine (PX4 ULog,
ArduPilot dataflash, MAVLink telemetry logs).

Public API:
    run_analysis(...)  → FlightMDReport
    FlightMDReport     — the report data model
    FlightMetadata     — flight metadata model
    Finding            — individual finding
    Severity / Category — enums

All diagnostics are produced by a deterministic rule engine — no network
access or API key is required. An optional AI enhancer can be passed in to
polish the executive summary; the platform is fully functional without it.

Usage:
    from flightmd_core import run_analysis, FlightMDReport
    report = await run_analysis(
        ulog_path="flight.ulg",
        file_name="flight.ulg",
        file_size=1234567,
    )
"""

from flightmd_core.orchestrator import run_analysis
from flightmd_core.models.findings import (
    FlightMDReport,
    Finding,
    AnalyserResult,
    ParamRecommendation,
    Severity,
    Category,
)
from flightmd_core.models.metadata import FlightMetadata

__version__ = "1.0.0"
__all__ = [
    "run_analysis",
    "FlightMDReport",
    "Finding",
    "AnalyserResult",
    "ParamRecommendation",
    "Severity",
    "Category",
    "FlightMetadata",
]
