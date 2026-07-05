"""
FlightMD Data Models — Permanent Data Contract
Schema version: 1.0

These models are consumed by the FlightMD web app AND by UAOP as a package import.
Do not rename fields. Do not add/remove fields without bumping schema_version.
"""

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
import uuid


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"
    GOOD     = "good"


class Category(str, Enum):
    OSCILLATION = "oscillation"
    VIBRATION   = "vibration"
    EKF         = "ekf"
    BATTERY     = "battery"
    GPS         = "gps"
    PARAMETERS  = "parameters"
    MOTORS      = "motors"
    SYSTEM      = "system"


class ParamRecommendation(BaseModel):
    param_name: str
    current_value: float
    suggested_value: float
    unit: Optional[str] = None
    change_direction: str        # "increase" | "decrease" | "set"
    reason: str                  # one-line reason


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: Category
    severity: Severity
    title: str
    technical_summary: str       # raw numbers, timestamps, axis labels
    plain_english: str           # rule-engine-generated, 2-4 sentences (optionally AI-polished)
    recommendation: str          # rule-engine-generated, 1-2 sentences, specific action
    confidence: float            # 0.0–1.0
    timestamp_start_ms: Optional[int] = None
    timestamp_end_ms: Optional[int] = None
    chart_data: Optional[dict] = None    # serialisable data for frontend charts
    param_changes: list[ParamRecommendation] = []


class AnalyserResult(BaseModel):
    analyser: str
    display_name: str
    findings: list[Finding]
    health_score: float = 100.0  # 0–100
    skipped: bool = False
    skip_reason: Optional[str] = None
    processing_ms: int = 0
    key_metrics: dict[str, float] = {}
    # Headline raw numbers computed regardless of whether a Finding fired
    # (e.g. oscillation peak Hz, battery sag per cell, max HDOP). Lets trend
    # analysis show gradual drift across flights before a threshold is ever
    # crossed — a health_score of 100 can still hide a metric creeping up.


class FlightMDReport(BaseModel):
    report_id: str
    schema_version: str = "1.3"          # bump when data contract changes — UAOP checks this
    overall_score: float
    score_label: str                     # Excellent/Good/Caution/Warning/Critical
    letter_grade: str                    # A-F grade based on overall_score
    executive_summary: str               # rule-engine-generated, 2-3 sentences (optionally AI-polished)
    metadata: "FlightMetadata"           # forward ref resolved at bottom
    findings: list[Finding]              # ALL findings, sorted severity desc
    param_change_sheet: list[ParamRecommendation]  # deduplicated across all analysers
    analyser_results: list[AnalyserResult]
    processing_time_ms: int
    file_name: str
    file_size_bytes: int


# Resolve forward reference
from flightmd_core.models.metadata import FlightMetadata  # noqa: E402
FlightMDReport.model_rebuild()
