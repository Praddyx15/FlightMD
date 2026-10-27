"""
End to end on the checked-in sample logs: the real pyulog / DFReader / mavutil readers,
the real format detector and the whole pipeline. See tests/sample_logs/README.md for
what these files are (and aren't).
"""

import json
import os

import pytest

from flightmd_core.__main__ import main as cli_main
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


async def _analyse(path: str):
    return await run_analysis(ulog_path=path, file_name=os.path.basename(path), file_size=os.path.getsize(path))


@pytest.mark.parametrize("ext,expected_format", FORMATS.items())
def test_format_autodetection(ext, expected_format):
    path = _sample_path("clean", ext)
    assert os.path.exists(path), f"Sample log missing: {path} — run scripts/generate_sample_logs.py"
    assert detect_format(path) == expected_format


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_clean_sample_has_no_findings(ext):
    report = await _analyse(_sample_path("clean", ext))
    assert report.overall_score == 100.0
    assert report.letter_grade == "A"
    assert report.findings == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flawed_sample_trips_oscillation_and_gps_findings(ext):
    report = await _analyse(_sample_path("flawed", ext))
    assert report.overall_score < 100.0
    titles = " ".join(f.title for f in report.findings)
    assert "Oscillation" in titles
    assert "GPS" in titles


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flawed_sample_key_metrics_show_the_underlying_drift(ext):
    # key_metrics carry the raw numbers the cross-flight trends chart
    report = await _analyse(_sample_path("flawed", ext))
    oscillation = next(ar for ar in report.analyser_results if ar.analyser == "oscillation")
    assert oscillation.key_metrics["roll_peak_hz"] == pytest.approx(1.1, abs=0.3)

    gps = next(ar for ar in report.analyser_results if ar.analyser == "gps")
    assert gps.key_metrics["min_satellites"] <= 8


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_gps_path_signal_quality_populated_across_formats(ext):
    report = await _analyse(_sample_path("flawed", ext))
    assert report.metadata.gps_path
    assert report.metadata.gps_path_hdop is not None
    assert len(report.metadata.gps_path_hdop) == len(report.metadata.gps_path)
    assert any(v is not None and v > 0 for v in report.metadata.gps_path_hdop)


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", FORMATS.keys())
async def test_flight_stats_populated_across_formats(ext):
    # .bin and .tlog have no vehicle_local_position; these come from the GPS track instead
    report = await _analyse(_sample_path("flawed", ext))
    md = report.metadata
    assert md.max_altitude_m is not None
    assert md.max_speed_ms is not None
    assert md.total_distance_m is not None
    assert 0 <= md.max_speed_ms < 100, "implausible speed, probably a duplicate-timestamp GPS row"
    assert md.max_altitude_m > 0
    assert md.total_distance_m > 0


@pytest.mark.asyncio
async def test_tlog_sample_is_armed_for_the_whole_log():
    report = await _analyse(_sample_path("clean", "tlog"))
    windows = report.metadata.armed_windows
    assert len(windows) == 1
    start, end = windows[0]
    assert start < 1.0
    assert end == pytest.approx(report.metadata.duration_seconds, abs=1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("ext", ["ulg", "bin"])
async def test_no_arming_info_is_reported(ext):
    report = await _analyse(_sample_path("clean", ext))
    assert report.metadata.armed_windows is None
    assert any("arming" in w for w in report.metadata.parse_warnings)


@pytest.mark.asyncio
async def test_offline_mode_skips_weather_and_geocoding():
    report = await _analyse(_sample_path("clean", "ulg"))
    assert report.metadata.location_name is None
    assert "offline" in report.metadata.weather["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name, data", [
    ("garbage.tlog", bytes(range(256)) * 40),
    ("notes.tlog", "﻿just some notes\n".encode("utf-16-be") * 200),
    ("empty.ulg", b""),
])
async def test_unanalysable_files_fail_closed(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    with pytest.raises(ValueError):
        await _analyse(str(p))


@pytest.mark.asyncio
async def test_size_limit(monkeypatch):
    monkeypatch.setenv("FLIGHTMD_MAX_LOG_MB", "0.001")
    with pytest.raises(ValueError, match="limit"):
        await _analyse(_sample_path("clean", "ulg"))


@pytest.mark.asyncio
async def test_parse_timeout(monkeypatch):
    # starting the worker process alone takes longer than this
    monkeypatch.setenv("FLIGHTMD_PARSE_TIMEOUT_S", "0.001")
    with pytest.raises(ValueError, match="took longer"):
        await _analyse(_sample_path("clean", "bin"))


def test_cli_writes_json(tmp_path, capsys):
    out = tmp_path / "report.json"
    assert cli_main([_sample_path("flawed", "ulg"), "--json", str(out)]) == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["file_name"] == "sample_flawed.ulg"
    assert "/100" in capsys.readouterr().out


def test_cli_rejects_garbage(tmp_path, capsys):
    p = tmp_path / "x.tlog"
    p.write_bytes(b"\xff\xfe" + b"hello" * 100)
    assert cli_main([str(p)]) == 1
    assert "error" in capsys.readouterr().err
