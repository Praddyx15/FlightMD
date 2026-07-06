"""
Integration tests against the real, checked-in sample logs — these run the
actual pyulog / pymavlink.DFReader / pymavlink.mavutil parsing code (not the
mocked readers used elsewhere), through the real format auto-detector and
the full analysis pipeline. See tests/sample_logs/README.md for how these
files were generated and what they do (and don't) prove.
"""

import os

import pytest

from flightmd_core.orchestrator import run_analysis
from flightmd_core.services.format_detector import detect_format

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample_logs")

FORMATS = {
    "ulg": "px4_ulog",
    "bin": "ardupilot_bin",
    "tlog": "mavlink_tlog",
}


def _sample_path(profile: str, ext: str) -> str:
    return os.path.join(SAMPLE_DIR, f"sample_{profile}.{ext}")


@pytest.mark.parametrize("ext,expected_format", FORMATS.items())
def test_format_autodetection(ext, expected_format):
    path = _sample_path("clean", ext)
    assert os.path.exists(path), f"Sample log missing: {path} — run scripts/generate_sample_logs.py"
    assert detect_format(path) == expected_format


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_clean_sample_has_no_findings(ext):
    report = await run_analysis(
        ulog_path=_sample_path("clean", ext),
        file_name=f"sample_clean.{ext}",
        file_size=os.path.getsize(_sample_path("clean", ext)),
    )
    assert report.overall_score == 100.0
    assert report.letter_grade == "A"
    assert report.findings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flawed_sample_trips_oscillation_and_gps_findings(ext):
    report = await run_analysis(
        ulog_path=_sample_path("flawed", ext),
        file_name=f"sample_flawed.{ext}",
        file_size=os.path.getsize(_sample_path("flawed", ext)),
    )
    assert report.overall_score < 100.0
    titles = " ".join(f.title for f in report.findings)
    assert "Oscillation" in titles
    assert "GPS" in titles


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flawed_sample_key_metrics_show_the_underlying_drift(ext):
    """key_metrics should surface the raw oscillation frequency and GPS
    numbers regardless of the findings text — this is what the cross-flight
    trend feature charts."""
    report = await run_analysis(
        ulog_path=_sample_path("flawed", ext),
        file_name=f"sample_flawed.{ext}",
        file_size=os.path.getsize(_sample_path("flawed", ext)),
    )
    oscillation = next(ar for ar in report.analyser_results if ar.analyser == "oscillation")
    assert oscillation.key_metrics["roll_peak_hz"] == pytest.approx(1.1, abs=0.3)

    gps = next(ar for ar in report.analyser_results if ar.analyser == "gps")
    assert gps.key_metrics["min_satellites"] <= 8


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_gps_path_signal_quality_populated_across_formats(ext):
    """gps_path_hdop is a per-point parallel array to gps_path, used to
    color the 3D flight path by GPS signal quality — available for all
    three formats since hdop lives in the same GPS topic as lat/lon."""
    report = await run_analysis(
        ulog_path=_sample_path("flawed", ext),
        file_name=f"sample_flawed.{ext}",
        file_size=os.path.getsize(_sample_path("flawed", ext)),
    )
    assert report.metadata.gps_path
    assert report.metadata.gps_path_hdop is not None
    assert len(report.metadata.gps_path_hdop) == len(report.metadata.gps_path)
    assert any(v is not None and v > 0 for v in report.metadata.gps_path_hdop)


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flight_stats_populated_across_formats(ext):
    """max_altitude_m/max_speed_ms/total_distance_m come from PX4's
    vehicle_local_position for ULog, but ArduPilot .bin and MAVLink .tlog
    have no such topic — the orchestrator falls back to deriving them from
    the universal GPS topic, so all three formats should end up populated
    with physically plausible values (a real dataflash log surfaced these
    fields silently staying None, and — before a gap-plausibility guard —
    a speed of tens of thousands of m/s from duplicate-timestamp GPS rows)."""
    report = await run_analysis(
        ulog_path=_sample_path("flawed", ext),
        file_name=f"sample_flawed.{ext}",
        file_size=os.path.getsize(_sample_path("flawed", ext)),
    )
    md = report.metadata
    assert md.max_altitude_m is not None
    assert md.max_speed_ms is not None
    assert md.total_distance_m is not None
    assert 0 <= md.max_speed_ms < 100, "implausible speed — likely a duplicate-timestamp GPS row divide-by-near-zero"
    assert md.max_altitude_m > 0
    assert md.total_distance_m > 0
