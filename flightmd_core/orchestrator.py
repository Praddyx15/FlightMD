"""
The analysis pipeline: open (and decompress) the log, detect the format, parse in a
child process, run the analysers, explain, score, build the report. run_analysis() is
the entry point for the API, the CLI and the tests.

Environment:
  FLIGHTMD_OFFLINE=1          no weather, geocoding or AI calls
  FLIGHTMD_MAX_LOG_MB         refuse bigger logs, compressed or not (default 512)
  FLIGHTMD_PARSE_TIMEOUT_S    stop the parser after this long (default 600; 0 = parse
                              in this process with no limit)
  FLIGHTMD_CACHE / FLIGHTMD_DATA_DIR   parsed-topic cache, see cache.py
"""

import asyncio
import hashlib
import inspect
import logging
import multiprocessing
import os
import pickle
import queue
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

from flightmd_core import cache
from flightmd_core.analysers.registry import load_analysers
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.services.ai_enhancer import AIEnhancer
from flightmd_core.services.compressed import open_log
from flightmd_core.services.format_detector import PARSERS, UnsupportedFormatError, detect_format
from flightmd_core.services.explanation_engine import ExplanationEngine
from flightmd_core.services.score_calculator import ScoreCalculator
from flightmd_core.services.report_builder  import ReportBuilder
from flightmd_core.services.weather_lookup import fetch_weather
from flightmd_core.services.geocoding import reverse_geocode

logger = logging.getLogger(__name__)

# The parse is most of the wall time, so it gets most of the bar.
PARSE_START, PARSE_END = 5, 60

# Rough parse speed per format (MB/s on an ordinary laptop), only for the first ETA
# before the parser has reported anything. Formats not listed use the default.
PARSE_MB_PER_S = {"px4_ulog": 12.0, "ardupilot_bin": 5.0, "ardupilot_log": 2.0, "mavlink_tlog": 3.0}
DEFAULT_MB_PER_S = 4.0
# everything after the parse: analysers, explanations, report
ANALYSIS_BASE_S = 2.0
ANALYSIS_S_PER_MB = 0.04

# Real GPS fixes don't come faster than ~20 Hz; closer rows are duplicates (seen at the
# end of real dataflash logs) and dividing by the tiny gap gives absurd speeds.
MIN_GPS_DT_S = 0.05
# no UAV we analyse gets near this; anything faster is a gltiched fix
MAX_PLAUSIBLE_SPEED_MS = 75.0
PATH_POINTS = 500


def offline() -> bool:
    return os.environ.get("FLIGHTMD_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse(log_format: str, path: str, report: Optional[Callable[[float], None]] = None):
    parser = PARSERS[log_format]()
    # the newer parsers take a progress callback; the others just parse
    if report is not None and "progress" in inspect.signature(parser.parse).parameters:
        return parser.parse(path, progress=report)
    return parser.parse(path)


def _child(log_format: str, path: str, q) -> None:
    last = [0.0]

    def report(frac: float) -> None:
        if frac - last[0] >= 0.01:
            last[0] = frac
            q.put(("progress", frac))

    try:
        q.put(("done", _parse(log_format, path, report)))
    except BaseException as e:
        try:
            pickle.dumps(e)
        except Exception:
            e = RuntimeError(f"{type(e).__name__}: {e}")
        q.put(("error", e))


def _parse_with_limit(log_format: str, path: str, timeout_s: float,
                      report: Optional[Callable[[float], None]] = None):
    """Parse in a child process so a runaway parse can actually be killed (a thread
    can't be). Progress comes back over the same queue as the result."""
    if timeout_s <= 0:
        return _parse(log_format, path, report)

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_child, args=(log_format, path, q), daemon=True)
    proc.start()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValueError(f"Parsing the log took longer than {timeout_s:.0f} s and was stopped.")
            try:
                kind, value = q.get(timeout=min(left, 1.0))
            except queue.Empty:
                if proc.is_alive():
                    continue
                try:
                    kind, value = q.get(timeout=1.0)
                except queue.Empty:
                    # killed from outside, usually out of memory
                    raise ValueError(
                        f"The parser process stopped unexpectedly (exit code {proc.exitcode})."
                    ) from None
            if kind == "progress":
                if report is not None:
                    report(value)
            elif kind == "error":
                raise value
            else:
                return value
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(5)
        q.close()


async def _open_and_parse(log_path, max_bytes, analysis_est_s, progress, loop):
    """Decompress if needed, detect the format and parse, reporting progress + ETA."""
    path, cleanup = await loop.run_in_executor(None, open_log, log_path, max_bytes)
    try:
        try:
            log_format = await loop.run_in_executor(None, detect_format, path)
        except UnsupportedFormatError as e:
            raise ValueError(str(e)) from e
        logger.info(f"Detected format: {log_format}")

        parse_mb = os.path.getsize(path) / 1e6
        first_eta = parse_mb / PARSE_MB_PER_S.get(log_format, DEFAULT_MB_PER_S) + analysis_est_s
        await progress(PARSE_START, "Parsing flight log…", first_eta)
        t0 = time.monotonic()

        def on_parse(frac: float) -> None:
            # runs on the parse thread, not the event loop
            spent = time.monotonic() - t0
            if frac > 0.02:
                eta = spent * (1 - frac) / frac + analysis_est_s
            else:
                eta = first_eta - spent
            pct = PARSE_START + int((PARSE_END - PARSE_START) * min(frac, 1.0))
            asyncio.run_coroutine_threadsafe(
                progress(pct, f"Parsing flight log… {frac:.0%}", max(eta, 0.0)), loop)

        timeout_s = _env_float("FLIGHTMD_PARSE_TIMEOUT_S", 600)
        try:
            topics, params, metadata = await loop.run_in_executor(
                None, _parse_with_limit, log_format, path, timeout_s, on_parse
            )
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to parse {log_format} file: {e}") from e
    finally:
        cleanup()

    metadata.source_format = log_format
    return topics, params, metadata


def _no_weather(reason: str) -> dict:
    return {
        "temperature_max_c": None,
        "temperature_min_c": None,
        "wind_speed_max_ms": None,
        "rain_sum_mm": None,
        "description": reason,
    }


async def run_analysis(
    ulog_path: str,
    file_name: str,
    file_size: int,
    progress_callback: Optional[Callable] = None,
    ai_enhancer: Optional[AIEnhancer] = None,
) -> FlightMDReport:
    """
    ulog_path is any supported log (.ulg, .bin, .tlog, ..., optionally .gz / .zip; the
    format is detected from the content). progress_callback is an optional
    callable(pct, message, eta_s), sync or async; eta_s is seconds left or None.
    ai_enhancer, when given and configured, only rewrites the executive summary;
    findings stay rule-based.

    Raises ValueError for a log that can't be analysed (unknown format, too big, no
    telemetry, parse failure or timeout).
    """
    start_ms = int(time.time() * 1000)
    loop = asyncio.get_running_loop()
    sent = [0]

    async def progress(pct: int, msg: str, eta_s: Optional[float] = None):
        # parse progress comes from another thread and can land late
        if pct < sent[0]:
            return
        sent[0] = pct
        if progress_callback:
            try:
                res = progress_callback(pct, msg, None if eta_s is None else round(eta_s, 1))
                if inspect.isawaitable(res):
                    await res
            except Exception:
                logger.warning("progress callback failed", exc_info=True)
        logger.info(f"[{pct}%] {msg}")

    max_mb = _env_float("FLIGHTMD_MAX_LOG_MB", 512)
    size_mb = os.path.getsize(ulog_path) / 1e6
    if size_mb > max_mb:
        raise ValueError(f"Log is {size_mb:.0f} MB; the limit is {max_mb:.0f} MB.")
    analysis_est_s = ANALYSIS_BASE_S + ANALYSIS_S_PER_MB * size_mb
    await progress(PARSE_START, "Reading flight log…", size_mb / DEFAULT_MB_PER_S + analysis_est_s)

    log_sha256 = await loop.run_in_executor(None, file_sha256, ulog_path)
    parsed = None
    if cache.enabled():
        try:
            parsed = await loop.run_in_executor(None, cache.get, log_sha256)
        except OSError:
            logger.warning("topic cache read failed", exc_info=True)

    if parsed is not None:
        topics, params, metadata = parsed
        logger.info(f"Parsed topics for {log_sha256[:12]} came from the cache")
        await progress(PARSE_END, "Using the earlier parse of this log…", analysis_est_s)
    else:
        topics, params, metadata = await _open_and_parse(
            ulog_path, int(max_mb * 1e6), analysis_est_s, progress, loop)
        metadata.log_sha256 = log_sha256
        if cache.enabled():
            try:
                # before anything below adds to metadata: the cache holds the parse only
                await loop.run_in_executor(None, cache.put, log_sha256, topics, params, metadata)
            except OSError:
                logger.warning("topic cache write failed", exc_info=True)

    # arming/landed state alone (a params-only tlog still has HEARTBEATs) isn't telemetry
    if not any(not k.startswith(("vehicle_status", "vehicle_land_detected")) for k in topics):
        raise ValueError(
            "No analysable telemetry in this log (no IMU, GPS, battery or ESC data), "
            "so there is nothing to score."
        )

    logger.info(
        f"Log parsed: {metadata.duration_seconds:.1f}s, "
        f"{len(topics)} topics, {len(params)} params"
    )
    analysis_t0 = time.monotonic()

    def eta_left() -> float:
        return max(analysis_est_s - (time.monotonic() - analysis_t0), 0.5)

    metadata.armed_windows = _armed_windows(topics, metadata.duration_seconds)
    if metadata.armed_windows is None:
        metadata.parse_warnings.append(
            "No arming information in this log, so the whole recording is treated as flight."
        )
    elif not metadata.armed_windows:
        metadata.parse_warnings.append("The vehicle never armed during this log.")

    track = _gps_track(topics)
    # print(len(track) if track is not None else 0, "gps rows")
    lat = lon = None
    if track is not None:
        lat, lon = float(track["lat"].iloc[0]), float(track["lon"].iloc[0])
        _fill_path(metadata, track, topics)

    # todo: weather and geocoding could go out together with asyncio.gather
    if lat is None:
        metadata.weather = _no_weather("No GPS position data in log")
    elif offline():
        metadata.weather = _no_weather("Weather lookup is off (offline mode)")
    else:
        await progress(62, "Fetching weather context…", eta_left())
        if metadata.log_start_utc:
            metadata.weather = await loop.run_in_executor(
                None, fetch_weather, lat, lon, metadata.log_start_utc
            )
        else:
            # no date means we'd be fetching today's weather for an old flight
            metadata.weather = _no_weather("Flight date unknown, so no weather lookup")
        metadata.location_name = await loop.run_in_executor(None, reverse_geocode, lat, lon)

    # only now: the parameter check picks its table from the firmware in metadata
    all_analysers = load_analysers(metadata=metadata)
    applicable = [a for a in all_analysers if a.missing_inputs(topics) is None]
    skipped    = [a for a in all_analysers if a.missing_inputs(topics) is not None]

    logger.info(
        f"Analysers: {len(applicable)} applicable, "
        f"{len(skipped)} skipped ({[a.name for a in skipped]})"
    )

    await progress(65, f"Running {len(applicable)} analysis modules concurrently…", eta_left())
    results = list(await asyncio.gather(*[
        loop.run_in_executor(None, a.safe_analyse, topics, params)
        for a in applicable
    ]))
    results += [a.skip_result(topics) for a in skipped]

    all_findings = [f for r in results for f in r.findings]
    logger.info(f"Total findings: {len(all_findings)}")

    # score first: the executive summary quotes it
    await progress(80, "Calculating health score…", eta_left())
    overall_score, score_label, letter_grade = ScoreCalculator().calculate(results)

    await progress(88, f"Generating deterministic explanations for {len(all_findings)} findings…", eta_left())
    engine = ExplanationEngine()
    try:
        all_findings = await engine.explain_findings(all_findings)
        executive_summary = await engine.generate_summary(
            metadata=metadata,
            findings=all_findings,
            overall_score=overall_score,
            score_label=score_label,
            results=results,
        )
    except Exception as e:
        logger.error(f"Explanation engine error: {e}")
        for f in all_findings:
            if not f.plain_english or f.plain_english == f.technical_summary:
                f.plain_english  = f.technical_summary
                f.recommendation = "Consult a PX4 expert for this finding."
        executive_summary = _fallback_summary(overall_score, score_label, all_findings)

    # AI only ever touches the summary, never a finding
    if ai_enhancer is not None and ai_enhancer.is_configured and not offline():
        await progress(92, "Polishing summary…", eta_left())
        executive_summary = await ai_enhancer.polish_summary(
            base_summary=executive_summary,
            findings=all_findings,
            metadata=metadata,
        )

    await progress(96, "Assembling report…", eta_left())
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

    await progress(100, "Done.", 0.0)
    return report


def _armed_windows(topics, end_s: float) -> Optional[list[list[float]]]:
    """[start_s, end_s] pairs where arming_state == 2; None if the log has no arming info."""
    vs = topics.get("vehicle_status")
    if vs is None or vs.empty or "arming_state" not in vs.columns:
        return None
    vs = vs.sort_values("timestamp")
    t = vs["timestamp"].to_numpy(dtype=float) / 1e6
    armed = (vs["arming_state"] == 2).to_numpy(dtype=int)
    edge = np.diff(armed)
    starts = list(t[1:][edge == 1])
    ends = list(t[1:][edge == -1])
    if armed[0]:
        starts.insert(0, t[0])
    if armed[-1]:
        ends.append(max(end_s, t[-1]))
    return [[round(float(a), 3), round(float(b), 3)] for a, b in zip(starts, ends)]


def _gps_track(topics) -> Optional[pd.DataFrame]:
    """timestamp / lat / lon (deg) / alt (m) / hdop for the map, from the receiver if
    there is one with a fix, else from the estimator's global position (tlogs)."""
    gps = topics.get("vehicle_gps_position")
    if gps is not None and "lat" in gps.columns and "lon" in gps.columns:
        ok = (gps["lat"] != 0) & (gps["lon"] != 0)
        if "fix_type" in gps.columns:
            ok &= gps["fix_type"] >= 2
        g = gps[ok]
        if not g.empty:
            alt_col = next((c for c in ["alt", "alt_ellipsoid"] if c in g.columns), None)
            hdop_col = next((c for c in ["hdop", "eph"] if c in g.columns), None)
            track = pd.DataFrame({
                "timestamp": g["timestamp"].astype("int64"),
                "lat": g["lat"] / 1e7,
                "lon": g["lon"] / 1e7,
                "alt": g[alt_col] / 1000.0 if alt_col else np.nan,  # mm
            })
            if hdop_col:
                track["hdop"] = g[hdop_col].astype(float)
            return track.sort_values("timestamp").reset_index(drop=True)

    gpos = topics.get("vehicle_global_position")
    if gpos is not None and "lat" in gpos.columns and "lon" in gpos.columns:
        g = gpos[(gpos["lat"] != 0) | (gpos["lon"] != 0)]
        if not g.empty:
            return pd.DataFrame({
                "timestamp": g["timestamp"].astype("int64"),
                "lat": g["lat"].astype(float),
                "lon": g["lon"].astype(float),
                "alt": g["alt"].astype(float) if "alt" in g.columns else np.nan,
            }).sort_values("timestamp").reset_index(drop=True)
    return None


def _none_if_nan(values) -> list[Optional[float]]:
    return [float(v) if np.isfinite(v) else None for v in values]


def _fill_path(metadata, track: pd.DataFrame, topics) -> None:
    step = max(1, len(track) // PATH_POINTS)
    sub = track.iloc[::step]

    metadata.gps_path = sub[["lat", "lon", "alt"]].astype(float).fillna(0.0).to_numpy().tolist()
    metadata.gps_path_t_s = [round(t / 1e6, 3) for t in sub["timestamp"].to_numpy(dtype=float)]
    if "hdop" in track.columns:
        metadata.gps_path_hdop = _none_if_nan(sub["hdop"].to_numpy(dtype=float))

    # bin/tlog have no vehicle_local_position, so the parser leaves these empty
    alt = track["alt"].to_numpy(dtype=float)
    alt = alt[np.isfinite(alt)]
    if metadata.max_altitude_m is None and alt.size:
        metadata.max_altitude_m = round(float(alt.max() - alt[0]), 1)

    if (metadata.max_speed_ms is None or metadata.total_distance_m is None) and len(track) > 1:
        lat = track["lat"].to_numpy(dtype=float)
        lon = track["lon"].to_numpy(dtype=float)
        ts_s = track["timestamp"].to_numpy(dtype=float) / 1e6
        # equirectangular is plenty at flight scale
        earth_r_m = 6371000.0
        dx = np.radians(lon - lon[0]) * earth_r_m * np.cos(np.radians(lat[0]))
        dy = np.radians(lat - lat[0]) * earth_r_m
        seg_dist = np.hypot(np.diff(dx), np.diff(dy))
        seg_dt = np.diff(ts_s)
        with np.errstate(divide="ignore", invalid="ignore"):
            seg_speed = np.where(seg_dt > 0, seg_dist / seg_dt, np.inf)
        plausible = (seg_dt >= MIN_GPS_DT_S) & (seg_speed <= MAX_PLAUSIBLE_SPEED_MS)

        if metadata.total_distance_m is None:
            metadata.total_distance_m = round(float(seg_dist[plausible].sum()), 1)
        if metadata.max_speed_ms is None and plausible.any():
            metadata.max_speed_ms = round(float(seg_speed[plausible].max()), 2)

    # wind per path point, PX4 estimator_status only
    est = topics.get("estimator_status")
    if est is None or "timestamp" not in est.columns:
        return
    wn = next((c for c in ["wind_vel_n", "wind[0]"] if c in est.columns), None)
    we = next((c for c in ["wind_vel_e", "wind[1]"] if c in est.columns), None)
    if not wn or not we:
        return
    wind = pd.DataFrame({
        "timestamp": est["timestamp"].astype("int64"),
        "wind_speed_ms": np.hypot(est[wn].astype(float), est[we].astype(float)),
    }).dropna().sort_values("timestamp")
    if wind.empty:
        return
    # sub is already in time order, so merge_asof keeps its rows lined up
    merged = pd.merge_asof(sub[["timestamp"]], wind, on="timestamp", direction="nearest")
    metadata.gps_path_wind_speed_ms = _none_if_nan(merged["wind_speed_ms"].to_numpy(dtype=float))


def _fallback_summary(score: float, label: str, findings: list) -> str:
    if not findings:
        return f"Flight analysed. Health score: {score:.0f}/100 ({label}). No significant findings detected."
    top = findings[0]
    return (
        f"Flight health: {score:.0f}/100 ({label}). "
        f"Top finding: [{top.severity.upper()}] {top.title}. "
        f"{len(findings)} finding(s) total — review the detailed report below."
    )
