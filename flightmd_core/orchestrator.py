"""
FlightMD Orchestrator — coordinates log parsing, analysis, explanation
generation, and report assembly.

This is the single entry point for the flightmd_core package.
Call run_analysis() from:
  - The FastAPI route handler (api/routers/analyse.py)
  - UAOP integration
  - CLI tools
  - Tests

Design: CPU-bound analysis runs in thread pool to avoid blocking the asyncio
event loop. All diagnostics are deterministic and require no network access;
an optional AI enhancer may be supplied to polish the executive summary.
"""

import asyncio
import logging
import time
from typing import Optional

import numpy as np
import pandas as pd

from flightmd_core.models.findings import FlightMDReport
from flightmd_core.services.ai_enhancer import AIEnhancer
from flightmd_core.services.ulog_parser     import ULogParser
from flightmd_core.services.ardupilot_parser import ArduPilotBinParser
from flightmd_core.services.mavlink_telemetry_parser import MavlinkTelemetryParser
from flightmd_core.services.format_detector import detect_format, UnsupportedFormatError
from flightmd_core.services.explanation_engine import ExplanationEngine
from flightmd_core.services.score_calculator import ScoreCalculator
from flightmd_core.services.report_builder  import ReportBuilder
from flightmd_core.services.weather_lookup import fetch_weather
from flightmd_core.services.geocoding import reverse_geocode
from flightmd_core.analysers import (
    OscillationAnalyser,
    VibrationAnalyser,
    EKFAnalyser,
    BatteryAnalyser,
    GPSAnalyser,
    ParameterAnalyser,
    MotorAnalyser,
    AscentProfileAnalyser,
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
    progress_callback: Optional[callable] = None,
    ai_enhancer: Optional[AIEnhancer] = None,
) -> FlightMDReport:
    """
    Full analysis pipeline.

    Args:
        ulog_path:          Path to the log file on disk. Format is
                             auto-detected: PX4 ULog (.ulg), ArduPilot
                             dataflash (.bin), or MAVLink telemetry (.tlog).
        file_name:          Original file name (stored in report)
        file_size:          File size in bytes (stored in report)
        progress_callback:  Optional async callable(progress: int, message: str)
        ai_enhancer:        Optional AIEnhancer. When omitted (default), behaviour
                             is identical to fully offline/deterministic operation.
                             When supplied and configured, only the executive
                             summary is polished — every finding's plain_english
                             and recommendation stay rule-based and reproducible.

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

    # ── Step 1: Detect format and parse ──────────────────────────────────────
    await progress(5, "Parsing flight log…")
    try:
        log_format = await loop.run_in_executor(None, lambda: detect_format(ulog_path))
    except UnsupportedFormatError as e:
        logger.error(f"Unsupported log format: {e}")
        raise ValueError(str(e)) from e

    parser = {
        "px4_ulog": ULogParser,
        "ardupilot_bin": ArduPilotBinParser,
        "mavlink_tlog": MavlinkTelemetryParser,
    }[log_format]()

    try:
        topics, params, metadata = await loop.run_in_executor(
            None,
            lambda: parser.parse(ulog_path),
        )
    except Exception as e:
        logger.error(f"Log parse failed ({log_format}): {e}")
        raise ValueError(f"Failed to parse {log_format} file: {e}") from e

    logger.info(f"Detected format: {log_format}")

    logger.info(
        f"Log parsed: {metadata.duration_seconds:.1f}s, "
        f"{len(topics)} topics, {len(params)} params"
    )

    # ── Step 1.5: Extract GPS Coordinates, GPS Path, and Weather ─────────────
    lat = None
    lon = None
    gps_path = None
    gps_path_hdop = None
    gps_path_wind_speed_ms = None

    if "vehicle_gps_position" in topics:
        gps_df = topics["vehicle_gps_position"]
        if "lat" in gps_df.columns and "lon" in gps_df.columns:
            # Filter out 0 or invalid coords
            valid_gps = gps_df[(gps_df["lat"] != 0) & (gps_df["lon"] != 0)]
            if not valid_gps.empty:
                # Initial position
                lat = float(valid_gps["lat"].iloc[0] / 1e7)
                lon = float(valid_gps["lon"].iloc[0] / 1e7)

                alt_col = next((c for c in ["alt", "alt_ellipsoid", "amsl"] if c in valid_gps.columns), None)
                hdop_col = next((c for c in ["hdop", "eph"] if c in valid_gps.columns), None)
                # downsample gps_path
                step = max(1, len(valid_gps) // 500)
                path_subset = valid_gps.iloc[::step]

                path_points = []
                hdop_points = []
                for _, row in path_subset.iterrows():
                    r_lat = float(row["lat"] / 1e7)
                    r_lon = float(row["lon"] / 1e7)
                    r_alt = float(row[alt_col] / 1000.0) if alt_col else 0.0 # convert mm to m
                    path_points.append([r_lat, r_lon, r_alt])
                    hdop_val = row[hdop_col] if hdop_col else None
                    hdop_points.append(float(hdop_val) if hdop_val is not None and pd.notna(hdop_val) else None)

                gps_path = path_points
                gps_path_hdop = hdop_points if hdop_col else None

                # Fallback flight stats derived straight from the GPS topic —
                # ulog_parser.py already computes these from PX4's
                # vehicle_local_position, but ArduPilot/MAVLink logs have no
                # such topic, so those fields would otherwise stay None.
                # Only fill in what the format-specific parser left empty.
                if metadata.max_altitude_m is None and alt_col:
                    alt_m = valid_gps[alt_col].to_numpy(dtype=float) / 1000.0
                    metadata.max_altitude_m = round(float(alt_m.max() - alt_m[0]), 1)

                if (metadata.max_speed_ms is None or metadata.total_distance_m is None) and "timestamp" in valid_gps.columns:
                    gps_lat = valid_gps["lat"].to_numpy(dtype=float) / 1e7
                    gps_lon = valid_gps["lon"].to_numpy(dtype=float) / 1e7
                    ts_s = valid_gps["timestamp"].to_numpy(dtype=float) / 1e6
                    if len(gps_lat) > 1:
                        # Equirectangular approximation — accurate enough at
                        # flight-line scales, far cheaper than true haversine.
                        lat0_rad = np.radians(gps_lat[0])
                        earth_r_m = 6371000.0
                        dx = np.radians(gps_lon - gps_lon[0]) * earth_r_m * np.cos(lat0_rad)
                        dy = np.radians(gps_lat - gps_lat[0]) * earth_r_m
                        seg_dist = np.hypot(np.diff(dx), np.diff(dy))
                        seg_dt = np.diff(ts_s)

                        # Real GPS fixes never arrive faster than ~20Hz — a
                        # smaller inter-sample gap means duplicate/near-
                        # duplicate log entries (observed at the tail of real
                        # dataflash logs, e.g. during landing/disarm), not
                        # genuine motion. Dividing a real-but-tiny distance by
                        # a near-zero gap explodes into an impossible speed.
                        MIN_GPS_DT_S = 0.05
                        # Second, independent guard: a single glitched fix
                        # (receiver multipath/cold-start, or a malformed log
                        # entry) can produce a huge jump even across a
                        # plausible time gap. No rotorcraft/fixed-wing UAV
                        # gets anywhere near this — it exists purely to
                        # reject corrupt coordinate outliers.
                        MAX_PLAUSIBLE_SPEED_MS = 75.0

                        with np.errstate(divide="ignore", invalid="ignore"):
                            seg_speed_raw = np.where(seg_dt > 0, seg_dist / seg_dt, np.inf)
                        plausible = (seg_dt >= MIN_GPS_DT_S) & (seg_speed_raw <= MAX_PLAUSIBLE_SPEED_MS)

                        if metadata.total_distance_m is None:
                            metadata.total_distance_m = round(float(seg_dist[plausible].sum()), 1)

                        if metadata.max_speed_ms is None and plausible.any():
                            metadata.max_speed_ms = round(float(seg_speed_raw[plausible].max()), 2)

                # Wind speed per path point (PX4 estimator_status only) —
                # cross-topic, so join by nearest timestamp rather than
                # relying on matching row order.
                if "estimator_status" in topics and "timestamp" in path_subset.columns:
                    est_df = topics["estimator_status"]
                    wind_n_col = next((c for c in ["wind_vel_n", "wind[0]"] if c in est_df.columns), None)
                    wind_e_col = next((c for c in ["wind_vel_e", "wind[1]"] if c in est_df.columns), None)
                    if wind_n_col and wind_e_col and "timestamp" in est_df.columns:
                        try:
                            wind_df = pd.DataFrame({
                                "timestamp": est_df["timestamp"],
                                "wind_speed_ms": np.sqrt(est_df[wind_n_col] ** 2 + est_df[wind_e_col] ** 2),
                            }).dropna().sort_values("timestamp")
                            path_ts_df = path_subset[["timestamp"]].sort_values("timestamp")
                            merged = pd.merge_asof(path_ts_df, wind_df, on="timestamp", direction="nearest")
                            # merge_asof re-sorts by timestamp — realign back to path_subset's original order
                            wind_by_ts = dict(zip(merged["timestamp"], merged["wind_speed_ms"]))
                            gps_path_wind_speed_ms = [
                                float(wind_by_ts[ts]) if pd.notna(wind_by_ts.get(ts)) else None
                                for ts in path_subset["timestamp"]
                            ]
                        except Exception as e:
                            logger.warning(f"Wind speed path join failed (non-fatal): {e}")

    metadata.gps_path = gps_path
    metadata.gps_path_hdop = gps_path_hdop
    metadata.gps_path_wind_speed_ms = gps_path_wind_speed_ms

    # Run weather fetch + reverse geocoding in the executor so we don't block
    if lat and lon:
        await progress(15, "Fetching weather context…")
        metadata.weather = await loop.run_in_executor(
            None,
            lambda: fetch_weather(lat, lon, metadata.log_start_utc)
        )
        metadata.location_name = await loop.run_in_executor(
            None,
            lambda: reverse_geocode(lat, lon)
        )
    else:
        metadata.weather = {
            "temperature_max_c": None,
            "temperature_min_c": None,
            "wind_speed_max_ms": None,
            "rain_sum_mm": None,
            "description": "No GPS position data in log",
        }

    # ── Step 2: Instantiate analysers ────────────────────────────────────────
    all_analysers = [
        OscillationAnalyser(),
        VibrationAnalyser(),
        EKFAnalyser(),
        BatteryAnalyser(),
        GPSAnalyser(),
        ParameterAnalyser(),
        MotorAnalyser(),
        AscentProfileAnalyser(),
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
    logger.info(f"Total findings: {len(all_findings)}")

    # ── Step 5: Generate score (needed for executive summary prompt) ─────────
    await progress(80, "Calculating health score…")
    score_calc = ScoreCalculator()
    overall_score, score_label, letter_grade = score_calc.calculate(results)

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

    # ── Step 6.5: Optional AI polish (executive summary only) ───────────────
    # Findings' plain_english/recommendation are never touched here — they
    # stay deterministic and reproducible regardless of this step.
    if ai_enhancer is not None and ai_enhancer.is_configured:
        await progress(92, "Polishing summary…")
        executive_summary = await ai_enhancer.polish_summary(
            base_summary=executive_summary,
            findings=all_findings,
            metadata=metadata,
        )

    # ── Step 7: Assemble final report ────────────────────────────────────────
    await progress(96, "Assembling report…")
    report = ReportBuilder().build(
        results=results,
        findings=all_findings,
        metadata=metadata,
        score=(overall_score, score_label, letter_grade),
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
