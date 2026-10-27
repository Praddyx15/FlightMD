"""
FlightMD report models: the data contract.

The web app and UAOP (as a package import) both consume these. Don't rename
fields; add new ones as optional, and bump schema_version when you do.
"""

import math
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"
    GOOD     = "good"


class Category(str, Enum):
    OSCILLATION     = "oscillation"
    VIBRATION       = "vibration"
    EKF             = "ekf"
    BATTERY         = "battery"
    GPS             = "gps"
    PARAMETERS      = "parameters"
    MOTORS          = "motors"
    ASCENT_PROFILE  = "ascent_profile"
    SYSTEM          = "system"


class ParamRecommendation(BaseModel):
    param_name: str
    current_value: float
    suggested_value: float
    unit: Optional[str] = None
    change_direction: str        # "increase" | "decrease" | "set"
    reason: str                  # one line


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: Category
    severity: Severity
    title: str
    technical_summary: str       # raw numbers, timestamps, axis labels
    plain_english: str           # 2-4 sentences, from the explanation templates
    recommendation: str          # 1-2 sentences, specific action
    confidence: float            # 0.0-1.0
    # Log-relative time of the problem. The ms pair is the original field,
    # the seconds pair (added in 1.6) is the same window as floats.
    timestamp_start_ms: Optional[int] = None
    timestamp_end_ms: Optional[int] = None
    t_start_s: Optional[float] = None
    t_end_s: Optional[float] = None
    chart_data: Optional[dict] = None    # serialisable data for frontend charts
    param_changes: list[ParamRecommendation] = []
    # 1.6: stable id of the check that fired (e.g. "gps.fix_lost"); the
    # explanation templates key on it, never on the title.
    kind: Optional[str] = None
    confidence_level: Optional[str] = None   # "high" | "medium" | "low"

    @model_validator(mode="after")
    def _fill_derived(self):
        c = self.confidence
        self.confidence = min(1.0, max(0.0, c)) if math.isfinite(c) else 0.0
        if self.confidence_level is None:
            if self.confidence >= 0.75:
                self.confidence_level = "high"
            elif self.confidence >= 0.4:
                self.confidence_level = "medium"
            else:
                self.confidence_level = "low"
        if self.t_start_s is None and self.timestamp_start_ms is not None:
            self.t_start_s = self.timestamp_start_ms / 1000.0
        if self.t_end_s is None and self.timestamp_end_ms is not None:
            self.t_end_s = self.timestamp_end_ms / 1000.0
        return self


class AnalyserResult(BaseModel):
    analyser: str
    display_name: str
    findings: list[Finding]
    health_score: float = 100.0  # 0–100, only meaningful when assessed
    skipped: bool = False
    skip_reason: Optional[str] = None
    processing_ms: int = 0
    # Headline numbers computed whether or not a Finding fired (oscillation
    # peak Hz, sag per cell, max HDOP...), so trends can show a metric
    # creeping up long before it crosses a threshold.
    key_metrics: dict[str, float] = {}
    # False = this module could not check anything, which is not the same
    # as a clean 100. A skipped module is never assessed.
    assessed: bool = True

    @model_validator(mode="after")
    def _skipped_is_unassessed(self):
        if self.skipped:
            self.assessed = False
        return self


class FlightMDReport(BaseModel):
    report_id: str
    schema_version: str = "1.6"          # UAOP and AeroAtlas check this
    overall_score: float                 # 0 when nothing could be assessed
    score_label: str                     # Excellent/Good/Caution/Warning/Critical, or "Not assessed"
    letter_grade: str                    # A-F, "-" when not assessed
    executive_summary: str
    metadata: "FlightMetadata"           # forward ref resolved at bottom
    findings: list[Finding]              # all findings, most severe first
    param_change_sheet: list[ParamRecommendation]  # deduplicated across analysers
    analyser_results: list[AnalyserResult]
    processing_time_ms: int
    file_name: str
    file_size_bytes: int
    # share of the scoring weight that was actually assessed, 0.0-1.0
    assessed_fraction: Optional[float] = None


from flightmd_core.models.metadata import FlightMetadata  # noqa: E402
FlightMDReport.model_rebuild()
