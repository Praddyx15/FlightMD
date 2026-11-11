"""
DJI flight records built with tests/dji_writer.py (an independent encoder of the layout
dji-log-parser documents) and parsed with DJIParser. v13+ decryption runs against a
faked DJI keychain service; nothing here touches the network.
"""

import base64
import json
import math
import os
import urllib.error

import numpy as np
import pytest

import dji_writer as dw
from flightmd_core.services import dji_parser as dp
from flightmd_core.services.dji_parser import DJIParser

LAT, LON = 47.3977420, 8.5455940
START_MS = 1_780_000_000_000      # 2026-05-28T20:26:40Z


def test_crc64_check_value():
    assert dp.crc64(0, b"123456789") == 0xE9C6D914C4B8D9CA


@pytest.mark.parametrize("seed, rtype", [(0, 1), (0x5A, 1), (0xFF, 22), (7, 0)])
def test_xor_key_matches_writer(seed, rtype):
    assert dp.xor_key(seed, rtype) == dw.xor_key(seed, rtype)
    payload = bytes(range(40))
    assert dp.xor_decode(dw.xor(payload, dw.xor_key(seed, rtype)), dp.xor_key(seed, rtype)) == payload


def flight_records(version, n=60, aes=None):
    """A short hop: on the ground, take off to 20 m, land. aes = (key, iv) encrypts the
    Base-feature records (v13+); returns the encoded records."""
    recs = []
    chain = [aes[1]] if aes else None
    # the record types that use the Base feature's key; v14 moved these three to their own
    base = {dw.OSD, dw.HOME} | ({dw.CENTER_BATTERY, dw.GIMBAL, dw.RC} if version == 13 else set())

    def add(rtype, payload, seed=0x5A):
        if aes and rtype in base:
            rec, nxt = dw.record(rtype, payload, version, seed=seed, aes=(aes[0], chain[0]))
            chain[0] = nxt
        else:
            rec, _ = dw.record(rtype, payload, version, seed=seed)
        recs.append(rec)

    add(dw.HOME, dw.home(LAT, LON, 420.0))
    add(dw.CUSTOM, dw.custom(START_MS))
    for k in range(n):
        flying = 10 <= k < 50
        h = 20.0 * math.sin(math.pi * (k - 10) / 40) if flying else 0.0
        add(dw.OSD, dw.osd(LAT + k * 1e-5, LON, h, vx=1.5, vy=0.0, vz=-0.5 if k < 30 else 0.5,
                          roll=2.0, pitch=-3.0, yaw=90.0, flight_mode=6 if k < 40 else 15,
                          on_ground=not flying, motors_on=5 <= k < 55, sats=14,
                          fly_time_s=k / 10), seed=k & 0xFF)
        if k % 10 == 0:
            add(dw.CENTER_BATTERY, dw.center_battery(90 - k // 10, 16.4 - k * 0.01, 8.0, 4, temp_c=31.0))
            add(dw.RC, dw.rc(aileron=1024 + 330, throttle=1684))
            add(dw.GIMBAL, dw.gimbal(-45.0, 0.0, 12.5))
            add(dw.DEFORM, bytes([0b0010_0111]))
    return recs


def write(tmp_path, data, name="DJIFlightRecord_2026-05-28.txt"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.mark.parametrize("version", [6, 10, 12])
def test_osd_topics(tmp_path, version):
    path = write(tmp_path, dw.build(flight_records(version), version, start_ms=START_MS))
    topics, params, meta = DJIParser().parse(path)
    assert params == {}

    gps = topics["vehicle_gps_position"]
    assert len(gps) == 60
    assert list(gps["timestamp"][:3]) == [0, 100_000, 200_000]
    assert gps["lat"].iloc[7] == round((LAT + 7e-5) * 1e7)
    assert gps["lon"].iloc[7] == round(LON * 1e7)
    assert (gps["fix_type"] == 3).all() and (gps["satellites_used"] == 14).all()
    assert gps["lat"].dtype == np.int64
    # absolute altitude = home altitude + height above take-off
    assert gps["alt"].iloc[30] == round((420.0 + 20.0) * 1000)

    lp = topics["vehicle_local_position"]
    assert lp["z"].iloc[30] == pytest.approx(-20.0)
    assert lp["vx"].iloc[0] == pytest.approx(1.5)
    assert lp["x"].iloc[10] == pytest.approx(math.radians(10e-5) * dp.EARTH_R_M, rel=1e-6)
    assert lp["y"].iloc[10] == pytest.approx(0.0, abs=1e-6)

    att = topics["vehicle_attitude"]
    assert att["roll"].iloc[0] == pytest.approx(math.radians(2.0))
    assert att["yaw"].iloc[0] == pytest.approx(math.radians(90.0))
    q = att[["q[0]", "q[1]", "q[2]", "q[3]"]].to_numpy()
    np.testing.assert_allclose((q ** 2).sum(axis=1), 1.0)

    st = topics["vehicle_status"]
    assert list(st["arming_state"]) == [1, 2, 2, 1]
    assert list(st["timestamp"]) == [0, 500_000, 4_000_000, 5_500_000]
    assert st["nav_state"].iloc[1] == 2      # P-GPS
    assert st["nav_state"].iloc[2] == 5      # Go Home

    land = topics["vehicle_land_detected"]
    assert list(land["landed"]) == [True, False, True]
    assert list(land["timestamp"]) == [0, 1_000_000, 5_000_000]

    assert meta.duration_seconds == pytest.approx(5.9)
    assert meta.arm_count == 1
    assert meta.log_start_utc == "2026-05-28T20:26:40Z"
    assert meta.vehicle_type == "Copter"
    assert meta.airframe_name == "Mavic Air 2"
    assert meta.max_altitude_m == pytest.approx(20.0)
    assert meta.flight_modes_used == ["Go Home", "P-GPS"]
    assert meta.parse_warnings == []


@pytest.mark.parametrize("version", [6, 10])
def test_battery_rc_gimbal(tmp_path, version):
    path = write(tmp_path, dw.build(flight_records(version), version))
    topics, _, _ = DJIParser().parse(path)

    bat = topics["battery_status"]
    assert len(bat) == 6
    assert bat["voltage_v"].iloc[0] == pytest.approx(16.4)
    assert bat["current_a"].iloc[0] == pytest.approx(8.0)     # logged negative, discharging
    assert bat["remaining"].iloc[1] == pytest.approx(0.89)
    assert bat["cell_count"].iloc[0] == 4
    if version >= 8:
        assert bat["temperature"].iloc[0] == pytest.approx(31.0, abs=0.1)
    else:
        assert np.isnan(bat["temperature"].iloc[0])
    assert list(bat["timestamp"][:2]) == [0, 1_000_000]

    rc = topics["manual_control_setpoint"]
    assert rc["roll"].iloc[0] == pytest.approx(0.5)
    assert rc["throttle"].iloc[0] == pytest.approx(1.0)
    assert rc["pitch"].iloc[0] == pytest.approx(0.0)

    g = topics["dji_gimbal"]
    assert g["pitch_deg"].iloc[0] == pytest.approx(-45.0)
    assert g["yaw_deg"].iloc[0] == pytest.approx(12.5)

    d = topics["dji_deform"]
    assert d["protected"].iloc[0]
    assert d["deform_status"].iloc[0] == 3 and d["deform_mode"].iloc[0] == 2


def test_smart_battery_group_wins_and_keeps_instances(tmp_path):
    recs = flight_records(10, n=20)
    for k in range(5):
        recs.append(dw.record(dw.SMART_BATTERY_GROUP, dw.battery_dynamic(0, 15.2, 12.5, 70, 4), 10)[0])
        recs.append(dw.record(dw.SMART_BATTERY_GROUP, dw.battery_dynamic(1, 15.1, 12.0, 69, 4), 10)[0])
    recs.append(dw.record(dw.SMART_BATTERY_GROUP, dw.battery_static(0, 5000), 10)[0])
    topics, _, _ = DJIParser().parse(write(tmp_path, dw.build(recs, 10)))
    bat, bat1 = topics["battery_status"], topics["battery_status_1"]
    assert len(bat) == 5 and len(bat1) == 5
    assert bat["voltage_v"].iloc[0] == pytest.approx(15.2)
    assert bat["current_a"].iloc[0] == pytest.approx(12.5)
    assert bat["remaining"].iloc[0] == pytest.approx(0.70)
    assert bat["temperature"].iloc[0] == pytest.approx(30.0)
    assert (bat["capacity"] == 5000).all()
    assert "capacity" not in bat1.columns


def test_start_time_falls_back_to_custom_record(tmp_path):
    path = write(tmp_path, dw.build(flight_records(10), 10, start_ms=0))
    _, _, meta = DJIParser().parse(path)
    assert meta.log_start_utc == "2026-05-28T20:26:40Z"


def test_damaged_record_and_jpeg_are_skipped(tmp_path):
    recs = flight_records(10, n=20)
    recs.insert(5, b"\xff\xd8" + b"\x10" * 50 + b"\xff\xd9")       # embedded thumbnail
    # a record whose length runs past its terminator; the reader resyncs on the 0xFF
    recs.insert(8, b"\x63\x05\x00\x00\xff")
    topics, _, meta = DJIParser().parse(write(tmp_path, dw.build(recs, 10)))
    assert len(topics["vehicle_gps_position"]) == 20
    assert meta.parse_warnings == ["1 damaged records were skipped."]


def test_no_gps_fix(tmp_path):
    recs = [dw.record(dw.OSD, dw.osd(0.0, 0.0, 0.0, gps_valid=False, sats=0), 10, seed=k)[0] for k in range(10)]
    topics, _, _ = DJIParser().parse(write(tmp_path, dw.build(recs, 10)))
    assert (topics["vehicle_gps_position"]["fix_type"] == 0).all()
    assert topics["vehicle_local_position"]["x"].isna().all()


def test_no_osd_records(tmp_path):
    recs = [dw.record(dw.HOME, dw.home(LAT, LON, 1.0), 10)[0]]
    with pytest.raises(ValueError, match="OSD"):
        DJIParser().parse(write(tmp_path, dw.build(recs, 10)))


def test_truncated_file(tmp_path):
    data = dw.build(flight_records(10), 10)
    with pytest.raises(ValueError, match="truncated"):
        DJIParser().parse(write(tmp_path, data[:500]))


@pytest.mark.parametrize("header", [
    b"\x00" * 16 + b"BUILD" + b"\x00" * 300,
    b"LOGH" + b"\x00" * 300,
])
def test_dat_is_refused(tmp_path, header):
    with pytest.raises(ValueError, match=".DAT"):
        DJIParser().parse(write(tmp_path, header, name="FLY042.DAT"))


# --- detection helper ---------------------------------------------------------

@pytest.mark.parametrize("version", [3, 6, 10, 12, 13])
def test_check_dji_txt(version):
    data = dw.build(flight_records(min(version, 12)), version) if version < 13 else _v13_file()[0]
    assert dp.check_dji_txt(data[:4096], complete=False) is True
    assert dp.check_dji_txt(data, complete=True) is True


def test_check_dji_txt_short_and_garbage():
    assert dp.check_dji_txt(b"\x00" * 8) is None
    assert dp.check_dji_txt(b"\x00" * 8, complete=True) is False
    assert dp.check_dji_txt(bytes(range(256)) * 4, complete=True) is False
    assert dp.check_dji_txt(b"plain text notes, not a flight record\n" * 20, complete=True) is False


# --- v13+: encrypted records --------------------------------------------------

KEY, IV = bytes(range(32)), bytes(range(100, 116))


def _v13_file(version=13):
    pytest.importorskip("cryptography")
    recs = [dw.key_storage(dw.BASE_FEATURE, b"wrapped-key-material", version)]
    recs += flight_records(version, n=30, aes=(KEY, IV))
    return dw.build(recs, version, start_ms=START_MS), recs


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self.error:
            raise self.error
        return FakeResponse(json.dumps(self.reply).encode())


def keychain_reply():
    return {
        "result": {"code": 0, "msg": "success"},
        "data": [[{
            "featurePoint": "FR_Standardization_Feature_Base_1",
            "aesKey": base64.b64encode(KEY).decode(),
            "aesIv": base64.b64encode(IV).decode(),
        }]],
    }


@pytest.fixture
def opener(monkeypatch):
    fake = FakeOpener(keychain_reply())
    monkeypatch.setattr(dp.urllib.request, "build_opener", lambda *handlers: fake)
    monkeypatch.setenv("DJI_API_KEY", "test-key")
    monkeypatch.delenv("FLIGHTMD_OFFLINE", raising=False)
    return fake


@pytest.mark.parametrize("version", [13, 14])
def test_v13_decrypts_with_fetched_keychain(tmp_path, opener, version):
    data, _ = _v13_file(version)
    topics, _, meta = DJIParser().parse(write(tmp_path, data))

    gps = topics["vehicle_gps_position"]
    assert len(gps) == 30
    assert gps["lat"].iloc[7] == round((LAT + 7e-5) * 1e7)
    assert topics["vehicle_status"]["arming_state"].iloc[1] == 2
    assert meta.log_start_utc == "2026-05-28T20:26:40Z"

    req = opener.requests[0]
    assert req.full_url == dp.KEYCHAIN_URL
    assert req.get_method() == "POST"
    assert req.get_header("Api-key") == "test-key"
    body = json.loads(req.data)
    assert body["version"] == 1 and body["department"] == 3
    assert body["keychainsArray"] == [[{
        "featurePoint": "FR_Standardization_Feature_Base_1",
        "aesCiphertext": base64.b64encode(b"wrapped-key-material").decode(),
    }]]


def test_v13_without_api_key(tmp_path, monkeypatch):
    data, _ = _v13_file()
    monkeypatch.delenv("DJI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DJI log v13\\+ needs DJI_API_KEY"):
        DJIParser().parse(write(tmp_path, data))


def test_v13_offline_never_calls_dji(tmp_path, opener, monkeypatch):
    data, _ = _v13_file()
    monkeypatch.setenv("FLIGHTMD_OFFLINE", "1")
    with pytest.raises(ValueError, match="DJI_API_KEY"):
        DJIParser().parse(write(tmp_path, data))
    assert opener.requests == []


def test_v13_rejected_key(tmp_path, opener):
    data, _ = _v13_file()
    opener.error = urllib.error.HTTPError(dp.KEYCHAIN_URL, 403, "Forbidden", {}, None)
    with pytest.raises(ValueError, match="rejected"):
        DJIParser().parse(write(tmp_path, data))


def test_v13_service_error_message(tmp_path, opener):
    data, _ = _v13_file()
    opener.reply = {"result": {"code": 1, "msg": "invalid sdk key"}, "data": None}
    with pytest.raises(ValueError, match="invalid sdk key"):
        DJIParser().parse(write(tmp_path, data))


def test_v13_records_without_a_key_are_skipped(tmp_path, opener):
    data, _ = _v13_file()
    reply = keychain_reply()
    reply["data"][0][0]["featurePoint"] = "FR_Standardization_Feature_Battery_13"
    opener.reply = reply
    with pytest.raises(ValueError, match="no readable OSD"):
        DJIParser().parse(write(tmp_path, data))


def test_checked_in_sample():
    path = os.path.join(os.path.dirname(__file__), "sample_logs", "sample_dji_v10.txt")
    topics, _, meta = DJIParser().parse(path)
    assert len(topics["vehicle_gps_position"]) == 900
    assert meta.duration_seconds == pytest.approx(89.9)
    assert meta.max_altitude_m == pytest.approx(40.0)
    assert meta.arm_count == 1
    assert meta.log_start_utc == "2026-04-18T09:30:00Z"
    assert list(topics["vehicle_land_detected"]["landed"]) == [True, False, True]
    assert len(topics["battery_status"]) == 90
