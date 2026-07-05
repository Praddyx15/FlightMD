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
