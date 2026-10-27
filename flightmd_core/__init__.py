"""
FlightMD core: flight log analysis for PX4 ULog, ArduPilot dataflash and MAVLink
telemetry logs. The diagnostics are a deterministic rule engine and need no network or
API key; an optional AI enhancer can polish the executive summary.

    from flightmd_core import run_analysis
    report = await run_analysis(ulog_path="flight.ulg", file_name="flight.ulg", file_size=1234567)

or from a shell: python -m flightmd_core flight.ulg --json report.json
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
