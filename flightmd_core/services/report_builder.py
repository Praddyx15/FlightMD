"""
ReportBuilder — assembles the final FlightMDReport from all analyser outputs.

Responsibilities:
  - Merge and deduplicate ParamRecommendations
  - Sort findings (CRITICAL first)
  - Populate all FlightMDReport fields
"""

import uuid
import time
from typing import Optional

from flightmd_core.models.findings import (
    Finding,
    AnalyserResult,
    FlightMDReport,
    ParamRecommendation,
    Severity,
)
from flightmd_core.models.metadata import FlightMetadata

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

        # Sort findings: CRITICAL → WARNING → INFO → GOOD, then by confidence desc
        sorted_findings = sorted(
            findings,
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), -f.confidence),
        )

        # Deduplicate param recommendations across all findings
        param_sheet = self._deduplicate_params(sorted_findings)

        # Processing time
        end_ms = int(time.time() * 1000)
        proc_ms = (end_ms - start_time_ms) if start_time_ms else 0

        return FlightMDReport(
            report_id=str(uuid.uuid4()),
            schema_version="1.2",
            overall_score=overall_score,
            score_label=score_label,
            letter_grade=letter_grade,
            executive_summary=executive_summary,
            metadata=metadata,
            findings=sorted_findings,
            param_change_sheet=param_sheet,
            analyser_results=results,
            processing_time_ms=proc_ms,
            file_name=file_name,
            file_size_bytes=file_size,
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _deduplicate_params(self, findings: list[Finding]) -> list[ParamRecommendation]:
        """
        Collect all ParamRecommendations across all findings.
        For duplicate param names, keep the one with the larger magnitude of change
        (most conservative recommendation).
        """
        seen: dict[str, ParamRecommendation] = {}

        for finding in findings:
            for rec in finding.param_changes:
                existing = seen.get(rec.param_name)
                if existing is None:
                    seen[rec.param_name] = rec
                else:
                    # Keep recommendation with larger absolute change
                    existing_change = abs(existing.suggested_value - existing.current_value)
                    new_change      = abs(rec.suggested_value - rec.current_value)
                    if new_change > existing_change:
                        seen[rec.param_name] = rec

        return list(seen.values())
