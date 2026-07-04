"""
FlightMD Orchestrator — coordinates ULog parsing, analysis, Claude AI, and report assembly.

This is the single entry point for the flightmd_core package.
Call run_analysis() from:
  - The FastAPI route handler (api/routers/analyse.py)
  - UAOP integration
  - CLI tools
  - Tests

Design: CPU-bound analysis runs in thread pool to avoid blocking the asyncio event loop.
Claude API calls are fully async and concurrent.
"""

import asyncio
import logging
import time
from typing import Optional

from flightmd_core.models.findings import FlightMDReport
from flightmd_core.services.ulog_parser     import ULogParser
from flightmd_core.services.explanation_engine import ExplanationEngine
from flightmd_core.services.score_calculator import ScoreCalculator
from flightmd_core.services.report_builder  import ReportBuilder
from flightmd_core.analysers import (
    OscillationAnalyser,
    VibrationAnalyser,
    EKFAnalyser,
    BatteryAnalyser,
    GPSAnalyser,
    ParameterAnalyser,
    MotorAnalyser,
)

logger = logging.getLogger(__name__)

# Progress milestone labels (reported via callback)
PROGRESS_STEPS = [
    (5,  "Parsing flight log…"),
    (20, "Running oscillation analysis…"),
    (35, "Analysing vibration & IMU health…"),
    (50, "Checking EKF and sensor fusion…"),
    (62, "Evaluating battery health…"),
    (72, "Reviewing GPS quality…"),
    (80, "Inspecting parameters & motors…"),
    (88, "Generating AI explanations…"),
    (96, "Assembling report…"),
]


async def run_analysis(
    ulog_path: str,
    file_name: str,
    file_size: int,
    anthropic_api_key: str,
    use_claude: bool = True,
    progress_callback: Optional[callable] = None,
) -> FlightMDReport:
    """
    Full analysis pipeline.

    Args:
        ulog_path:          Path to the .ulg file on disk
        file_name:          Original file name (stored in report)
        file_size:          File size in bytes (stored in report)
        anthropic_api_key:  Anthropic API key for Claude
        use_claude:         If False, skip Claude and use technical_summary as plain_english
        progress_callback:  Optional async callable(progress: int, message: str)

    Returns:
        FlightMDReport (fully populated)
    """
    start_ms = int(time.time() * 1000)
    loop = asyncio.get_event_loop()

    async def progress(pct: int, msg: str):
        if progress_callback:
            try:
                await progress_callback(pct, msg)
            except Exception:
                pass
        logger.info(f"[{pct}%] {msg}")

    # ── Step 1: Parse ULog ───────────────────────────────────────────────────
    await progress(5, "Parsing flight log…")
    try:
        topics, params, metadata = await loop.run_in_executor(
            None,
            lambda: ULogParser().parse(ulog_path),
        )
    except Exception as e:
        logger.error(f"ULog parse failed: {e}")
        raise ValueError(f"Failed to parse ULog file: {e}") from e

    logger.info(
        f"Log parsed: {metadata.duration_seconds:.1f}s, "
        f"{len(topics)} topics, {len(params)} params"
    )

    # ── Step 2: Instantiate analysers ────────────────────────────────────────
    all_analysers = [
        OscillationAnalyser(),
        VibrationAnalyser(),
        EKFAnalyser(),
        BatteryAnalyser(),
        GPSAnalyser(),
        ParameterAnalyser(),
        MotorAnalyser(),
    ]

    available_topics = set(topics.keys())
    applicable = [a for a in all_analysers if a.is_applicable(available_topics)]
    skipped    = [a for a in all_analysers if not a.is_applicable(available_topics)]

    logger.info(
        f"Analysers: {len(applicable)} applicable, "
        f"{len(skipped)} skipped ({[a.name for a in skipped]})"
    )

    # ── Step 3: Run all applicable analysers concurrently ───────────────────
    await progress(20, f"Running {len(applicable)} analysis modules concurrently…")

    analyser_tasks = [
        loop.run_in_executor(None, a.safe_analyse, topics, params)
        for a in applicable
    ]
    results = list(await asyncio.gather(*analyser_tasks))

    # Add skipped results for completeness
    from flightmd_core.models.findings import AnalyserResult
    for a in skipped:
        results.append(AnalyserResult(
            analyser=a.name,
            display_name=a.display_name,
            findings=[],
            skipped=True,
            skip_reason=f"Required topics not available: {a.required_topics}",
        ))

    # ── Step 4: Collect findings ─────────────────────────────────────────────
    all_findings = [f for r in results for f in r.findings]
    logger.info(f"Total findings before Claude: {len(all_findings)}")

    # ── Step 5: Generate score (needed for executive summary prompt) ─────────
    await progress(80, "Calculating health score…")
    score_calc = ScoreCalculator()
    overall_score, score_label = score_calc.calculate(results)

    # ── Step 6: Deterministic explanations ───────────────────────────────────
    await progress(88, f"Generating deterministic explanations for {len(all_findings)} findings…")
    engine = ExplanationEngine()
    try:
        all_findings = await engine.explain_findings(all_findings)
        executive_summary = await engine.generate_summary(
            metadata=metadata,
            findings=all_findings,
            overall_score=overall_score,
            score_label=score_label,
        )
    except Exception as e:
        logger.error(f"Explanation engine error: {e}")
        # Fallback to technical summaries
        for f in all_findings:
            if not f.plain_english or f.plain_english == f.technical_summary:
                f.plain_english  = f.technical_summary
                f.recommendation = "Consult a PX4 expert for this finding."
        executive_summary = _fallback_summary(overall_score, score_label, all_findings)

    # ── Step 7: Assemble final report ────────────────────────────────────────
    await progress(96, "Assembling report…")
    report = ReportBuilder().build(
        results=results,
        findings=all_findings,
        metadata=metadata,
        score=(overall_score, score_label),
        executive_summary=executive_summary,
        file_name=file_name,
        file_size=file_size,
        start_time_ms=start_ms,
    )

    elapsed_ms = int(time.time() * 1000) - start_ms
    logger.info(
        f"Analysis complete: {report.report_id}, "
        f"score={overall_score}/100 ({score_label}), "
        f"{len(all_findings)} findings, "
        f"{elapsed_ms}ms"
    )

    await progress(100, "Done.")
    return report


def _fallback_summary(score: float, label: str, findings: list) -> str:
    if not findings:
        return f"Flight analysed. Health score: {score:.0f}/100 ({label}). No significant findings detected."
    top = findings[0]
    return (
        f"Flight health: {score:.0f}/100 ({label}). "
        f"Top finding: [{top.severity.upper()}] {top.title}. "
        f"{len(findings)} finding(s) total — review the detailed report below."
    )
