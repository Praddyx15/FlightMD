"""
End-to-end verification of newly added log formats in FlightMD:
- ArduPilot DataFlash Text Log (.log)
- Betaflight / INAV Blackbox Log (.bbl)
- DJI App Flight Records (.txt, v6/v10/v12)
- Gzip Compressed Archives (.gz)
- Zip Compressed Archives (.zip)
- Safe rejection of unsupported DJI .DAT archives
"""

import gzip
import json
import math
import zipfile
import pytest

from flightmd_core.orchestrator import run_analysis
from flightmd_core.services.format_detector import detect_format, UnsupportedFormatError
from flightmd_core.services.dji_parser import DAT_UNSUPPORTED
import tests.blackbox_writer as bw
import tests.dji_writer as dw

# Coordinates for test trajectories
LAT, LON = 47.397742, 8.545594
START_MS = 1_700_000_000_000
ARM, ANGLE = 1 << 0, 1 << 1


def make_ardupilot_text_log(duration_s: int = 15) -> str:
    """Generates a complete multi-second ArduPilot text dataflash log."""
    lines = [
        "FMT, 128, 89, FMT, BBnNZ, Type,Length,Name,Format,Columns",
        "FMT, 64, 31, PARM, QNf, TimeUS,Name,Value",
        "FMT, 91, 75, MSG, QZ, TimeUS,Message",
        "FMT, 129, 45, IMU, QBffffff, TimeUS,I,GyrX,GyrY,GyrZ,AccX,AccY,AccZ",
        "FMT, 130, 50, GPS, QBBIHBcLLeffffB, TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U",
        "FMT, 147, 47, BAT, QBfffffcf, TimeUS,Inst,Volt,VoltR,Curr,CurrTot,EnrgTot,Temp,Res",
        "FMT, 163, 19, EV, QB, TimeUS,Id",
        "MSG, 1000, ArduCopter V4.5.2 (abcdef12)",
        "PARM, 2000, BATT_CAPACITY, 5000",
        "PARM, 2000, ATC_RAT_RLL_P, 0.135",
        "PARM, 2000, ATC_RAT_PIT_P, 0.135",
        "PARM, 2000, MOT_SPIN_ARM, 0.12",
        "EV, 1000000, 10",  # Arm event (EV 10)
    ]

    for sec in range(duration_s):
        t_us = (sec + 1) * 1_000_000
        for step in range(10):
            sub_t = t_us + step * 100_000
            lines.append(f"IMU, {sub_t}, 0, 0.0050, 0.0050, 0.0010, 0.0200, 0.0200, -9.8066")

        lat_step = -35.3632621 + sec * 0.0001
        lon_step = 149.1652374 + sec * 0.0001
        alt_m = 584.0 + sec * 1.5
        lines.append(f"GPS, {t_us}, 0, 3, 123456000, 2300, 14, 0.75, {lat_step:.7f}, {lon_step:.7f}, {alt_m:.2f}, 4.20, 45.0, 0.1, 45.0, 1")

        v = max(14.8, 16.6 - sec * 0.05)
        curr = 15.0 + (sec % 3) * 2.0
        lines.append(f"BAT, {t_us}, 0, {v:.2f}, {v:.2f}, {curr:.2f}, {sec * 4:.1f}, 1.5, 28.0, 0.008")

    lines.append(f"EV, {(duration_s + 1) * 1_000_000}, 11")  # Disarm event (EV 11)
    return "\n".join(lines) + "\n"


def make_betaflight_bbl_log(n_iterations: int = 1000) -> bytes:
    """Generates a complete multi-iteration Betaflight blackbox log."""
    w = bw.BlackboxWriter()
    w.header().slow(ARM | ANGLE)
    w.gps_home(round(LAT * 1e7), round(LON * 1e7))

    start_time = 1_000_000
    dt = 2000  # 500 Hz (2 ms)

    for it in range(n_iterations):
        t = start_time + it * dt
        v = {
            "time": t & 0xFFFFFFFF,
            "axisI[0]": 0, "axisI[1]": 0, "axisI[2]": 0,
            "rcCommand[0]": 0, "rcCommand[1]": 0, "rcCommand[2]": 0, "rcCommand[3]": 1500,
            "setpoint[0]": 0, "setpoint[1]": 0, "setpoint[2]": 0, "setpoint[3]": 400,
            "vbatLatest": 1650 - (it // 100),
            "amperageLatest": 1200 + (it % 10),
            "magADC[0]": 0, "magADC[1]": 0, "magADC[2]": 0,
            "gyroADC[0]": round(50 * math.sin(2 * math.pi * it / 100)),
            "gyroADC[1]": 2, "gyroADC[2]": 0,
            "accSmooth[0]": 0, "accSmooth[1]": 0, "accSmooth[2]": 2048,
            "motor[0]": 1400, "motor[1]": 1400, "motor[2]": 1400, "motor[3]": 1400,
            "eRPM[0]": 700, "eRPM[1]": 700, "eRPM[2]": 700, "eRPM[3]": 700,
        }
        w.main(it, v)
        if w.logged(it) and it % 100 == 50:
            w.gps_frame(t + 100, 14, round((LAT + it * 1e-6) * 1e7), round((LON + it * 1e-6) * 1e7), 1234, speed=450, course=900)

    w.event_flight_mode(ANGLE, ARM | ANGLE)
    w.end()
    return w.bytes()


def make_dji_flight_log(version: int = 10, n: int = 60) -> bytes:
    """Generates a synthetic DJI flight record (.txt) with OSD, home, and battery frames."""
    recs = []

    def add(rtype, payload, seed=0x5A):
        rec, _ = dw.record(rtype, payload, version, seed=seed)
        recs.append(rec)

    add(dw.HOME, dw.home(LAT, LON, 420.0))
    add(dw.CUSTOM, dw.custom(START_MS))
    for k in range(n):
        flying = 10 <= k < 50
        h = 20.0 * math.sin(math.pi * (k - 10) / 40) if flying else 0.0
        add(
            dw.OSD,
            dw.osd(
                LAT + k * 1e-5, LON, h,
                vx=1.5, vy=0.0, vz=-0.5 if k < 30 else 0.5,
                roll=2.0, pitch=-3.0, yaw=90.0,
                flight_mode=6 if k < 40 else 15,
                on_ground=not flying,
                motors_on=5 <= k < 55,
                sats=14,
                fly_time_s=k / 10,
                battery=85 - (k // 10),
                drone_type=58,  # Mavic Air 2
            ),
            seed=k & 0xFF
        )
        if k % 10 == 0:
            add(
                dw.CENTER_BATTERY,
                dw.center_battery(
                    percent=85 - (k // 10),
                    volts=16.4 - (k // 10) * 0.1,
                    amps=8.0,
                    cells=4,
                    temp_c=30.0,
                ),
                seed=(k + 1) & 0xFF
            )

    return dw.build(recs, version=version, start_ms=START_MS)


@pytest.mark.asyncio
async def test_ardupilot_text_log_end_to_end(tmp_path):
    """Verifies format detection and full analysis of ArduPilot text .log format."""
    log_file = tmp_path / "flight_test.log"
    log_file.write_text(make_ardupilot_text_log(duration_s=10), encoding="ascii")

    fmt = detect_format(str(log_file))
    assert fmt == "ardupilot_log"

    report = await run_analysis(
        ulog_path=str(log_file),
        file_name=log_file.name,
        file_size=log_file.stat().st_size,
    )

    assert report.metadata.source_format == "ardupilot_log"
    assert report.metadata.vehicle_type == "Copter"
    assert "ArduCopter" in (report.metadata.firmware_version or "")
    assert report.metadata.duration_seconds == pytest.approx(10.0, abs=1.0)
    assert report.overall_score is not None
    assert report.overall_score > 70.0
    assert report.letter_grade in ["A", "B", "C"]

    json_str = report.model_dump_json()
    assert "NaN" not in json_str
    parsed = json.loads(json_str)
    assert parsed["report_id"] == report.report_id


@pytest.mark.asyncio
async def test_betaflight_bbl_log_end_to_end(tmp_path):
    """Verifies format detection and full analysis of Betaflight blackbox .bbl format."""
    log_file = tmp_path / "quad_session.bbl"
    log_file.write_bytes(make_betaflight_bbl_log(n_iterations=600))

    fmt = detect_format(str(log_file))
    assert fmt == "betaflight_bbl"

    report = await run_analysis(
        ulog_path=str(log_file),
        file_name=log_file.name,
        file_size=log_file.stat().st_size,
    )

    assert report.metadata.source_format == "betaflight_bbl"
    assert report.metadata.duration_seconds is not None
    assert report.overall_score is not None
    assert report.overall_score > 60.0

    json_str = report.model_dump_json()
    assert "NaN" not in json_str
    parsed = json.loads(json_str)
    assert parsed["metadata"]["source_format"] == "betaflight_bbl"


@pytest.mark.asyncio
@pytest.mark.parametrize("dji_version", [6, 10, 12])
async def test_dji_flight_record_end_to_end(tmp_path, dji_version):
    """Verifies format detection and full analysis of DJI flight records (.txt)."""
    log_file = tmp_path / f"DJIFlightRecord_v{dji_version}.txt"
    log_file.write_bytes(make_dji_flight_log(version=dji_version, n=60))

    fmt = detect_format(str(log_file))
    assert fmt == "dji_txt"

    report = await run_analysis(
        ulog_path=str(log_file),
        file_name=log_file.name,
        file_size=log_file.stat().st_size,
    )

    assert report.metadata.source_format == "dji_txt"
    assert report.metadata.vehicle_type == "Copter"
    assert report.metadata.duration_seconds == pytest.approx(5.9, abs=0.5)
    assert report.overall_score is not None

    json_str = report.model_dump_json()
    assert "NaN" not in json_str
    parsed = json.loads(json_str)
    assert parsed["metadata"]["vehicle_type"] == "Copter"


@pytest.mark.asyncio
async def test_gzip_compressed_log_end_to_end(tmp_path):
    """Verifies transparent extraction and full analysis of Gzip-compressed logs (.gz)."""
    raw_text = make_ardupilot_text_log(duration_s=6).encode("ascii")
    gz_file = tmp_path / "flight_archive.log.gz"
    with gzip.open(gz_file, "wb") as gz:
        gz.write(raw_text)

    report = await run_analysis(
        ulog_path=str(gz_file),
        file_name=gz_file.name,
        file_size=gz_file.stat().st_size,
    )

    assert report.metadata.source_format == "ardupilot_log"
    assert report.metadata.duration_seconds == pytest.approx(6.0, abs=1.0)
    assert report.overall_score is not None

    json_str = report.model_dump_json()
    assert "NaN" not in json_str
    assert json.loads(json_str)["overall_score"] == report.overall_score


@pytest.mark.asyncio
async def test_zip_compressed_log_end_to_end(tmp_path):
    """Verifies transparent extraction and full analysis of Zip-compressed logs (.zip)."""
    raw_text = make_ardupilot_text_log(duration_s=8).encode("ascii")
    zip_file = tmp_path / "mission_logs.zip"
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("subfolder/inner_flight.log", raw_text)

    report = await run_analysis(
        ulog_path=str(zip_file),
        file_name=zip_file.name,
        file_size=zip_file.stat().st_size,
    )

    assert report.metadata.source_format == "ardupilot_log"
    assert report.metadata.duration_seconds == pytest.approx(8.0, abs=1.0)
    assert report.overall_score is not None

    json_str = report.model_dump_json()
    assert "NaN" not in json_str
    assert json.loads(json_str)["overall_score"] == report.overall_score


def test_dji_dat_refused_with_unsupported_message(tmp_path):
    """Verifies that proprietary DJI .DAT files are rejected safely with an explanation."""
    dat_file = tmp_path / "FLY001.DAT"
    dat_file.write_bytes(b"LOGH\x00\x00\x00\x00" + b"\x00" * 200)

    with pytest.raises(UnsupportedFormatError) as exc_info:
        detect_format(str(dat_file))

    assert DAT_UNSUPPORTED in str(exc_info.value)
