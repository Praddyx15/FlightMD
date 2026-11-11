"""
Blackbox decoder primitives against the documented encodings, and whole synthetic logs
from tests/blackbox_writer.py (an independent encoder) through BetaflightParser.
"""

import math
import os
import random

import numpy as np
import pytest

import blackbox_writer as bw
from flightmd_core.services import betaflight_parser as bp
from flightmd_core.services.betaflight_parser import BetaflightParser

LAT, LON = 473_977_420, 85_455_940   # degE7
ARM, ANGLE = 1 << 0, 1 << 1


# --- primitives --------------------------------------------------------------

@pytest.mark.parametrize("data, value", [
    (b"\x01", 1), (b"\x2a", 42), (b"\x7f", 127), (b"\x80\x01", 128),
    (b"\x81\x01", 129), (b"\xa0\xb7\x01", 23456), (b"\xff\xff\xff\xff\x0f", 0xFFFFFFFF),
])
def test_unsigned_vb(data, value):
    assert bp.read_uvb(data, 0) == (value, len(data))


def test_unsigned_vb_reads_from_offset():
    assert bp.read_uvb(b"\x00\x80\x01\x05", 1) == (128, 3)


def test_unsigned_vb_longer_than_32_bits_is_corrupt():
    with pytest.raises(bp.BlackboxError):
        bp.read_uvb(b"\xff\xff\xff\xff\xff\x01", 0)


def test_unsigned_vb_cut_off():
    with pytest.raises(bp._Truncated):
        bp.read_uvb(b"\x80\x80", 0)


@pytest.mark.parametrize("value, folded", [
    (0, 0), (-1, 1), (1, 2), (-2, 3), (2147483647, 4294967294), (-2147483648, 4294967295),
])
def test_zigzag(value, folded):
    assert bp.zigzag_decode(folded) == value
    assert bw.zigzag(value) == folded


@pytest.mark.parametrize("value", [0, 1, -1, 63, -64, 64, 1000, -1000, 2**31 - 1, -(2**31)])
def test_signed_vb_round_trip(value):
    data = bw.svb(value)
    assert bp.read_svb(data, 0) == (value, len(data))


def test_signed_vb_spec_example():
    # motor deltas 205, 1, -1, 42 from the format description
    data = bytes([0x9A, 0x03, 0x02, 0x01, 0x54])
    out, pos = [], 0
    for _ in range(4):
        v, pos = bp.read_svb(data, pos)
        out.append(v)
    assert out == [205, 1, -1, 42]


@pytest.mark.parametrize("v, bits, expected", [
    (0b11, 2, -1), (0b01, 2, 1), (0xF, 4, -1), (0x7, 4, 7), (0x20, 6, -32),
    (0x80, 8, -128), (0x7FFF, 16, 32767), (0x8000, 16, -32768), (0x800000, 24, -8388608),
])
def test_sign_extend(v, bits, expected):
    assert bp.sign_extend(v, bits) == expected


@pytest.mark.parametrize("value", [0, -1, -5, -200, 100])
def test_neg_14bit(value):
    data = bw.neg14(value)
    assert bp.read_neg_14bit(data, 0) == (value, len(data))


def test_tag8_8svb_group():
    data = bw.tag8_8svb([0, 0, 4, 0, 8])
    assert data[0] == 0b00010100
    assert bp.read_tag8_8svb(data, 0, 5) == ([0, 0, 4, 0, 8], len(data))


def test_tag8_8svb_single_field_has_no_header():
    assert bw.tag8_8svb([-3]) == bw.svb(-3)
    assert bp.read_tag8_8svb(bw.svb(-3), 0, 1) == ([-3], 1)


@pytest.mark.parametrize("values, nbytes", [
    ([0, -1, 1], 1),                  # 2-bit fields
    ([-8, 7, 3], 2),                  # 4-bit
    ([-32, 31, 0], 3),                # 6-bit
    ([127, -128, 5], 4),              # 8-bit each
    ([300, -2, 70000], 1 + 2 + 1 + 3),
    ([2**31 - 1, -(2**31), 0], 1 + 4 + 4 + 1),
])
def test_tag2_3s32(values, nbytes):
    data = bw.tag2_3s32(values)
    assert len(data) == nbytes
    assert bp.read_tag2_3s32(data, 0) == (values, nbytes)


@pytest.mark.parametrize("values, nbytes", [
    ([1, -2, 0], 1),           # 2 bits each
    ([15, -16, 7], 2),         # 5, 5, 4 bits
    ([-128, 63, -64], 3),      # 8, 7, 7 bits
    ([1000, 0, 0], 1 + 2 + 1 + 1),
])
def test_tag2_3svariable(values, nbytes):
    data = bw.tag2_3svariable(values)
    assert len(data) == nbytes
    assert bp.read_tag2_3svariable(data, 0) == (values, nbytes)


def test_tag8_4s16_spec_example():
    data = bytes([0b01010010, 0x0D, 0x42])
    assert bp.read_tag8_4s16(data, 0) == ([13, 0, 4, 2], 3)


@pytest.mark.parametrize("values", [
    [0, 0, 0, 0], [-8, 7, 0, 1], [3, -100, 0, 0], [5, 1000, -3, 0],   # 8 and 16 bits off a nibble
    [-32768, 32767, -1, 127], [0, 0, 0, -32768],
])
def test_tag8_4s16_round_trip(values):
    data = bw.tag8_4s16(values)
    assert bp.read_tag8_4s16(data, 0) == (values, len(data))


def test_tag8_4s16_data_version_1():
    # v1: two 4-bit fields share a byte (low nibble first), 16-bit is little endian
    data = bytes([0b11_10_01_01, 0x2F, 0x80, 0x34, 0x12])
    assert bp.read_tag8_4s16(data, 0, version=1) == ([-1, 2, -128, 0x1234], 5)


def test_random_round_trips():
    rng = random.Random(7)
    for _ in range(3000):
        mag = rng.choice([2, 8, 30, 200, 40000, 2**31 - 1])
        v3 = [rng.randint(-mag, mag - 1) for _ in range(3)]
        assert bp.read_tag2_3s32(bw.tag2_3s32(v3), 0)[0] == v3
        assert bp.read_tag2_3svariable(bw.tag2_3svariable(v3), 0)[0] == v3
        v4 = [rng.randint(-min(mag, 32768), min(mag, 32768) - 1) for _ in range(4)]
        assert bp.read_tag8_4s16(bw.tag8_4s16(v4), 0)[0] == v4


def test_header_and_field_defs():
    w = bw.BlackboxWriter().header()
    headers, pos = bp.parse_header(w.bytes(), 0)
    assert pos == len(w.bytes())
    assert headers["Firmware revision"].startswith("Betaflight 4.4.2")
    defs = bp.frame_defs(headers)
    assert defs["P"].names == defs["I"].names
    assert defs["I"].predictor[defs["I"].index["motor[0]"]] == bp.PRED_MINMOTOR
    assert defs["P"].encoding[defs["I"].index["loopIteration"]] == bp.ENC_NULL


def test_header_without_fields_is_rejected():
    with pytest.raises(bp.BlackboxError):
        bp.frame_defs({"Data version": "2"})


# --- whole logs --------------------------------------------------------------

def values_at(it, t):
    return {
        "time": t & 0xFFFFFFFF,
        **{f"axisI[{k}]": 10 * k + it % 7 - 3 for k in range(3)},
        **{f"rcCommand[{k}]": 1500 + (it % 11) * 3 if k == 3 else (it % 17) - 8 for k in range(4)},
        **{f"setpoint[{k}]": round(300 * math.sin(it / 15 + k)) for k in range(3)},
        "setpoint[3]": 400 + it % 5,
        "vbatLatest": 1650 - it // 10,
        "amperageLatest": 1234 + it % 5,
        **{f"magADC[{k}]": (it * 3 + k) % 50 - 25 for k in range(3)},
        **{f"gyroADC[{k}]": round(100 * math.sin(2 * math.pi * it / 40 + k)) for k in range(3)},
        **{f"accSmooth[{k}]": (2048 if k == 2 else 0) + it % 9 - 4 for k in range(3)},
        # starts below motorOutput's 158, so motor[0]'s I-frame residual is negative
        **{f"motor[{k}]": 100 + 5 * k + (it % 13) * 20 for k in range(4)},
        **{f"eRPM[{k}]": 700 + k + it % 3 for k in range(4)},
    }


def build(n=300, start_time=5_000_000, dt=500, gps=True, end=True, writer=None, junk_after=None, **kw):
    w = writer or bw.BlackboxWriter(**kw)
    w.header().slow(ARM | ANGLE)
    if gps:
        w.gps_home(LAT, LON)
    logged = []
    for it in range(n):
        t = start_time + it * dt
        v = values_at(it, t)
        w.main(it, v)
        if w.logged(it):
            logged.append((it, t, v))
            if gps and it % 100 == 50:
                w.gps_frame(t + 100, 12, LAT + it, LON - it, 1234, speed=550, course=900)
        if it == junk_after:
            w.raw(b"\x07")
    w.event_flight_mode(ANGLE, ARM | ANGLE)
    if end:
        w.end()
    return w.bytes(), logged


def parse(tmp_path, data, name="flight.bbl"):
    p = tmp_path / name
    p.write_bytes(data)
    return BetaflightParser().parse(str(p))


def test_topics_and_units(tmp_path):
    data, logged = build()
    topics, params, meta = parse(tmp_path, data)

    t0 = logged[0][1]
    gyro = topics["vehicle_angular_velocity"]
    assert len(gyro) == len(logged)
    assert list(gyro["timestamp"]) == [t - t0 for _, t, _ in logged]
    want = np.array([[v[f"gyroADC[{k}]"] for k in range(3)] for _, _, v in logged]) * math.pi / 180
    np.testing.assert_allclose(gyro[["rollspeed", "pitchspeed", "yawspeed"]].to_numpy(), want)

    sp = topics["vehicle_rates_setpoint"]
    np.testing.assert_allclose(sp["roll"], [v["setpoint[0]"] * math.pi / 180 for _, _, v in logged])

    acc = topics["sensor_accel"]
    np.testing.assert_allclose(acc["z"], [v["accSmooth[2]"] / 2048 * 9.80665 for _, _, v in logged])

    out = topics["actuator_outputs"]
    assert list(out["output[0]"]) == [v["motor[0]"] for _, _, v in logged]
    assert list(out["output[3]"]) == [v["motor[3]"] for _, _, v in logged]
    assert (out["noutputs"] == 4).all()

    esc = topics["esc_status"]
    assert (esc["esc_count"] == 4).all()
    np.testing.assert_allclose(esc["esc[1].esc_rpm"], [v["eRPM[1]"] * 100 / 7 for _, _, v in logged])


def test_battery(tmp_path):
    data, logged = build()
    topics, _, _ = parse(tmp_path, data)
    bat = topics["battery_status"]
    ts = np.array([t - logged[0][1] for _, t, _ in logged])
    # thinned to one row per 10 ms
    assert len(bat) == len(np.unique(ts // 10_000))
    first = logged[0][2]
    assert bat["voltage_v"].iloc[0] == pytest.approx(first["vbatLatest"] / 100)
    assert bat["current_a"].iloc[0] == pytest.approx(first["amperageLatest"] / 100)


def test_gps(tmp_path):
    data, logged = build()
    topics, _, _ = parse(tmp_path, data)
    gps = topics["vehicle_gps_position"]
    assert list(gps["lat"]) == [LAT + 50, LAT + 150, LAT + 250]
    assert list(gps["lon"]) == [LON - 50, LON - 150, LON - 250]
    assert (gps["alt"] == 123_400).all()          # 1234 dm
    assert (gps["fix_type"] == 3).all()
    assert (gps["satellites_used"] == 12).all()
    assert gps["vel_m_s"].iloc[0] == pytest.approx(5.5)
    assert gps["cog_rad"].iloc[0] == pytest.approx(math.pi / 2)
    t50 = next(t for it, t, _ in logged if it == 50) - logged[0][1]
    assert gps["timestamp"].iloc[0] == t50 + 100
    assert gps["lat"].dtype == np.int64


def test_arming_from_slow_frames_and_events(tmp_path):
    data, logged = build()
    topics, _, meta = parse(tmp_path, data)
    st = topics["vehicle_status"]
    assert list(st["arming_state"]) == [2, 1]
    assert list(st["nav_state"]) == [15, 15]
    assert st["timestamp"].iloc[0] == 0
    assert st["timestamp"].iloc[1] == logged[-1][1] - logged[0][1]
    assert meta.arm_count == 1
    assert meta.flight_modes_used == ["Angle / Horizon"]


def test_params_and_metadata(tmp_path):
    data, logged = build()
    _, params, meta = parse(tmp_path, data)
    assert params["rollPID_P"] == 45
    assert params["rollPID_D"] == 40
    assert params["minthrottle"] == 1070
    assert params["motorOutput[0]"] == 158
    assert "Data version" not in params and "I interval" not in params
    assert "gyro_scale" not in params    # hex float bits, not a setting
    assert meta.firmware_version == "Betaflight 4.4.2 (4b26d4ac0) STM32F7X2"
    assert meta.hardware_id == "TEST FAKEBOARD"
    assert meta.log_start_utc == "2026-05-01T10:15:30Z"
    assert meta.duration_seconds == round((logged[-1][1] - logged[0][1]) / 1e6, 2)
    assert meta.parse_warnings == []
    assert "vehicle_angular_velocity" in meta.available_topics


def test_no_clock_on_the_board(tmp_path):
    data, _ = build(headers={"Log start datetime": "0000-01-01T00:00:00.000+00:00"})
    _, _, meta = parse(tmp_path, data)
    assert meta.log_start_utc is None


def test_skipped_p_frames(tmp_path):
    # P interval 1/4: only every 4th loop iteration is logged
    data, logged = build(p_denom=4)
    assert len(logged) == 75
    topics, _, _ = parse(tmp_path, data)
    gyro = topics["vehicle_angular_velocity"]
    assert len(gyro) == len(logged)
    np.testing.assert_allclose(gyro["rollspeed"], [v["gyroADC[0]"] * math.pi / 180 for _, _, v in logged])


def test_time_rollover(tmp_path):
    # uptime in us wraps at 2^32 (71 minutes)
    data, logged = build(start_time=2**32 - 20_000)
    topics, _, _ = parse(tmp_path, data)
    ts = topics["vehicle_angular_velocity"]["timestamp"].to_numpy()
    assert ts[0] == 0
    assert (np.diff(ts) == 500).all()


def test_high_resolution_gyro(tmp_path):
    data, logged = build(headers={"blackbox_high_resolution": "1"})
    topics, _, _ = parse(tmp_path, data)
    want = logged[5][2]["gyroADC[0]"] / 10 * math.pi / 180
    assert topics["vehicle_angular_velocity"]["rollspeed"].iloc[5] == pytest.approx(want)


def test_missing_acc_1g_skips_accel(tmp_path):
    w = bw.BlackboxWriter()
    del w.headers["acc_1G"]
    data, _ = build(writer=w)
    topics, _, meta = parse(tmp_path, data)
    assert "sensor_accel" not in topics
    assert any("acc_1G" in m for m in meta.parse_warnings)


def test_rpm_from_debug_fields(tmp_path):
    fields = [f for f in bw.DEFAULT_FIELDS if not f[0].startswith("eRPM")]
    fields += [(f"debug[{i}]", 1, bw.P_ZERO, bw.E_SVB, bw.P_AVG2, bw.E_SVB) for i in range(4)]
    w = bw.BlackboxWriter(fields=fields, headers={"debug_mode": "45", "motor_poles": "12"})
    w.header().slow(ARM)
    rows = []
    for it in range(100):
        v = values_at(it, 1_000_000 + it * 500)
        for k in range(4):
            v[f"debug[{k}]"] = 500 + k * 10 + it % 4
        w.main(it, v)
        rows.append(v)
    topics, _, _ = parse(tmp_path, w.end().bytes())
    esc = topics["esc_status"]
    np.testing.assert_allclose(esc["esc[2].esc_rpm"], [v["debug[2]"] * 100 / 6 for v in rows])


def test_debug_fields_in_another_mode_are_not_rpm(tmp_path):
    fields = [f for f in bw.DEFAULT_FIELDS if not f[0].startswith("eRPM")]
    fields += [(f"debug[{i}]", 1, bw.P_ZERO, bw.E_SVB, bw.P_AVG2, bw.E_SVB) for i in range(4)]
    w = bw.BlackboxWriter(fields=fields, headers={"debug_mode": "6"})
    w.header()
    for it in range(40):
        v = values_at(it, 1_000_000 + it * 500)
        v.update({f"debug[{k}]": 3 for k in range(4)})
        w.main(it, v)
    topics, _, _ = parse(tmp_path, w.end().bytes())
    assert "esc_status" not in topics


def test_inav_names_and_no_arming(tmp_path):
    fields = [(("vbat" if f[0] == "vbatLatest" else "amperage" if f[0] == "amperageLatest" else f[0]), *f[1:])
              for f in bw.DEFAULT_FIELDS]
    w = bw.BlackboxWriter(fields=fields, headers={
        "Firmware type": "INAV", "Firmware revision": "INAV 7.1.0 (abcdef0) MATEKF405"})
    w.header().slow(ARM)
    for it in range(64):
        v = values_at(it, 1_000_000 + it * 1000)
        v["vbat"], v["amperage"] = v.pop("vbatLatest"), v.pop("amperageLatest")
        w.main(it, v)
    topics, _, _ = parse(tmp_path, w.end().bytes())
    assert topics["battery_status"]["voltage_v"].iloc[0] == pytest.approx(16.5)
    assert "vehicle_status" not in topics


def test_largest_of_several_logs_is_analysed(tmp_path):
    short, _ = build(n=64, gps=False)
    long_, logged = build(n=300)
    topics, _, meta = parse(tmp_path, short + long_)
    assert len(topics["vehicle_angular_velocity"]) == len(logged)
    assert any("2 blackbox logs" in m and "log 2" in m for m in meta.parse_warnings)


def test_junk_before_the_log_is_ignored(tmp_path):
    data, logged = build()
    topics, _, _ = parse(tmp_path, b"\x00\xffMSP junk" * 10 + data, name="LOG00001.TXT")
    assert len(topics["vehicle_angular_velocity"]) == len(logged)


def test_damaged_frames_are_skipped(tmp_path):
    clean, _, _ = parse(tmp_path, build()[0])
    # a stray byte after frame 100: that frame can't be trusted, and the P frames
    # after it can't be decoded until the next I frame (128)
    topics, _, meta = parse(tmp_path, build(junk_after=100)[0])
    gyro = topics["vehicle_angular_velocity"]
    ref = clean["vehicle_angular_velocity"]
    assert len(gyro) < len(ref)
    assert any("damaged" in m for m in meta.parse_warnings)
    np.testing.assert_allclose(gyro["rollspeed"].iloc[:100], ref["rollspeed"].iloc[:100])
    assert ref["timestamp"].iloc[150] in set(gyro["timestamp"])


def test_recovers_after_a_long_dropout(tmp_path):
    # 5800 loop iterations missing: more than one frame-to-frame jump may be, so the
    # first I frame after the gap is held back until the next one confirms it
    w = bw.BlackboxWriter().header().slow(ARM)
    for it in list(range(200)) + list(range(6016, 6200)):
        w.main(it, values_at(it, 1_000_000 + it * 500))
    topics, _, meta = parse(tmp_path, w.end().bytes())
    ts = set(topics["vehicle_angular_velocity"]["timestamp"])
    assert 6048 * 500 in ts and 6016 * 500 not in ts
    assert len(ts) == 200 + (6200 - 6048)
    assert any("damaged" in m for m in meta.parse_warnings)


def test_padding_after_end_of_log(tmp_path):
    data, logged = build()
    topics, _, meta = parse(tmp_path, data + b"\x00" * 64 + b"\xff" * 64)
    assert len(topics["vehicle_angular_velocity"]) == len(logged)
    assert meta.parse_warnings == []


def test_truncated_file(tmp_path):
    data, logged = build(end=False)
    topics, _, _ = parse(tmp_path, data[:-4])
    assert len(logged) - 2 <= len(topics["vehicle_angular_velocity"]) <= len(logged)


def test_not_a_blackbox_log(tmp_path):
    with pytest.raises(ValueError, match="blackbox"):
        parse(tmp_path, b"just text\n" * 20)


def test_header_only(tmp_path):
    w = bw.BlackboxWriter().header()
    with pytest.raises(ValueError, match="no decodable frames"):
        parse(tmp_path, w.bytes())


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        BetaflightParser().parse("does/not/exist.bbl")


def test_checked_in_sample():
    path = os.path.join(os.path.dirname(__file__), "sample_logs", "sample_betaflight.bbl")
    topics, params, meta = BetaflightParser().parse(path)
    gyro = topics["vehicle_angular_velocity"]
    assert len(gyro) == 20_000
    assert (np.diff(gyro["timestamp"]) == 1000).all()
    assert len(topics["vehicle_gps_position"]) == 200
    assert meta.duration_seconds == pytest.approx(20.0, abs=0.01)
    assert meta.parse_warnings == []
    # the 28 Hz roll wobble starts at 8 s
    roll = np.degrees(gyro["rollspeed"].to_numpy())
    assert np.abs(roll[:7000]).max() < 5
    assert np.abs(roll[10000:]).max() > 40
