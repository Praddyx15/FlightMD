"""
Assembles the FlightMDReport: findings sorted most severe first, one
parameter-change sheet without contradictions, and every number made
JSON-safe (NaN/inf -> None) so the API never emits a bare NaN.
"""

import math
import time
import uuid
from typing import Optional

from flightmd_core.analysers.helpers import clean
from flightmd_core.models.findings import (
    Finding,
    AnalyserResult,
    FlightMDReport,
    ParamRecommendation,
    Severity,
)
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.score_calculator import ScoreCalculator

SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.WARNING:  1,
    Severity.INFO:     2,
    Severity.GOOD:     3,
}


class ReportBuilder:
    def build(
        self,
        results: list[AnalyserResult],
        findings: list[Finding],
        metadata: FlightMetadata,
        score: tuple[float, str, str],         # (score, label, letter_grade) from ScoreCalculator
        executive_summary: str,
        file_name: str,
        file_size: int,
        start_time_ms: Optional[int] = None,
    ) -> FlightMDReport:
        overall_score, score_label, letter_grade = score

        for f in findings:
            self._sanitise_finding(f)
        for r in results:
            r.key_metrics = {k: float(v) for k, v in r.key_metrics.items()
                             if v is not None and math.isfinite(v)}
            if not math.isfinite(r.health_score):
                r.health_score = 0.0
            for f in r.findings:
                self._sanitise_finding(f)

        sorted_findings = sorted(
            findings,
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), -f.confidence),
        )
        param_sheet = self._deduplicate_params(sorted_findings)

        proc_ms = int(time.time() * 1000) - start_time_ms if start_time_ms else 0

        return FlightMDReport(
            report_id=str(uuid.uuid4()),
            overall_score=overall_score if math.isfinite(overall_score) else 0.0,
            score_label=score_label,
            letter_grade=letter_grade,
            executive_summary=executive_summary,
            metadata=self._sanitise_metadata(metadata),
            findings=sorted_findings,
            param_change_sheet=param_sheet,
            analyser_results=results,
            processing_time_ms=proc_ms,
            file_name=file_name,
            file_size_bytes=file_size,
            assessed_fraction=ScoreCalculator().assessed_fraction(results),
        )

    def _sanitise_finding(self, f: Finding) -> None:
        if f.chart_data is not None:
            f.chart_data = clean(f.chart_data)
        f.param_changes = [
            p for p in f.param_changes
            if math.isfinite(p.current_value) and math.isfinite(p.suggested_value)
        ]

    def _sanitise_metadata(self, metadata: FlightMetadata) -> FlightMetadata:
        data = clean(metadata.model_dump())
        if data.get("duration_seconds") is None:
            data["duration_seconds"] = 0.0
        return type(metadata).model_validate(data)

    def _deduplicate_params(self, findings: list[Finding]) -> list[ParamRecommendation]:
        """One entry per parameter. Findings arrive most severe first, so the
        first recommendation for a parameter wins; a later one that pulls the
        other way is noted on it instead of silently replacing it (the sheet
        used to say "increase" while a finding card said "decrease")."""
        seen: dict[str, ParamRecommendation] = {}
        conflicts: dict[str, list[str]] = {}

        for finding in findings:
            for rec in finding.param_changes:
                kept = seen.get(rec.param_name)
                if kept is None:
                    seen[rec.param_name] = rec.model_copy()
                elif rec.change_direction != kept.change_direction:
                    conflicts.setdefault(rec.param_name, []).append(
                        f"{rec.change_direction} to {rec.suggested_value:g} ({finding.title})"
                    )

        for name, notes in conflicts.items():
            rec = seen[name]
            rec.reason = f"{rec.reason} Another check suggests: {'; '.join(notes)}. Review before changing."
        return list(seen.values())
