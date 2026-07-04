"""
flightmd_core — PX4 ULog analysis engine.

Public API:
    run_analysis(...)  → FlightMDReport
    FlightMDReport     — the report data model
    FlightMetadata     — flight metadata model
    Finding            — individual finding
    Severity / Category — enums

Usage:
    from flightmd_core import run_analysis, FlightMDReport
    report = await run_analysis(
        ulog_path="flight.ulg",
        file_name="flight.ulg",
        file_size=1234567,
        anthropic_api_key="sk-ant-...",
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
