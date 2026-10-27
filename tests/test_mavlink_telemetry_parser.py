"""
MavlinkTelemetryParser field mapping, with pymavlink's log reader replaced by fake
messages using real MAVLink field names. tests/test_sample_logs.py runs the real reader.
"""

import struct

import numpy as np
import pytest

from flightmd_core.services.mavlink_telemetry_parser import MavlinkTelemetryParser

T0 = 1_700_000_000.0  # GCS receive time, epoch seconds


class FakeMavMessage:
    def __init__(self, mtype: str, timestamp: float, sys_id=1, comp=1, **fields):
        self._mtype = mtype
        self._timestamp = timestamp
        self._src = (sys_id, comp)
        for k, v in fields.items():
            setattr(self, k, v)

    def get_type(self) -> str:
        return self._mtype

    def get_srcSystem(self):
        return self._src[0]

    def get_srcComponent(self):
        return self._src[1]


class FakeMavConnection:
    def __init__(self, messages):
        self._messages = iter(messages)
        self.closed = False

    def recv_match(self, type=None):
        for m in self._messages:
            if type is None or m.get_type() in type:
                return m
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def tmp_tlog_path(tmp_path):
    p = tmp_path / "flight.tlog"
    p.write_bytes(b"\x00" * 8)  # only has to exist, the reader is faked
    return str(p)


def parse(monkeypatch, path, messages):
    from pymavlink import mavutil
    conn = FakeMavConnection(messages)
    monkeypatch.setattr(mavutil, "mavlogfile", lambda *a, **k: conn)
    out = MavlinkTelemetryParser().parse(path)
    assert conn.closed
    return out


def heartbeat(t, armed=True, autopilot=3, mav_type=2, custom_mode=0, **kw):
    base = 1 | (128 if armed else 0)
    return FakeMavMessage("HEARTBEAT", t, type=mav_type, autopilot=autopilot, base_mode=base,
                          custom_mode=custom_mode, system_status=4, mavlink_version=3, **kw)


def attitude(t, boot_ms, rate=0.1, **kw):
    return FakeMavMessage("ATTITUDE", t, time_boot_ms=boot_ms, roll=0.0, pitch=0.0, yaw=0.0,
                          rollspeed=rate, pitchspeed=0.2, yawspeed=0.3, **kw)


def gps_raw(t, fix=3, sats=11, lat=377749000, lon=-1224194000):
    return FakeMavMessage("GPS_RAW_INT", t, time_usec=0, fix_type=fix, lat=lat, lon=lon, alt=100000,
                          eph=150, epv=200, vel=500, cog=0, satellites_visible=sats)


def test_attitude_maps_to_angular_velocity(monkeypatch, tmp_tlog_path):
    messages = [attitude(T0, 0, 0.1), attitude(T0 + 0.1, 100, 0.15)]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    gyro = topics["vehicle_angular_velocity"]
    assert list(gyro["rollspeed"]) == pytest.approx([0.1, 0.15])
    assert list(gyro["yawspeed"]) == pytest.approx([0.3, 0.3])


def test_timestamps_are_vehicle_time_not_receive_time(monkeypatch, tmp_tlog_path):
    # a radio burst: three samples 50 ms apart on the vehicle arrive together
    messages = [
        attitude(T0, 1000),
        attitude(T0 + 0.5, 1050),
        attitude(T0 + 0.5, 1100),
        attitude(T0 + 0.5, 1150),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert list(topics["vehicle_angular_velocity"]["timestamp"]) == [0, 50_000, 100_000, 150_000]


def test_raw_imu_accel_converted_to_ms2(monkeypatch, tmp_tlog_path):
    # mG; 1000 mG = 9.80665 m/s^2
    messages = [
        FakeMavMessage("RAW_IMU", T0, time_usec=0, xacc=0, yacc=0, zacc=1000,
                       xgyro=0, ygyro=0, zgyro=0, xmag=0, ymag=0, zmag=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    assert topics["sensor_accel"]["z"].iloc[0] == pytest.approx(9.80665)
    assert "sensor_accel_0" not in topics


def test_imu_instances_and_source_priority(monkeypatch, tmp_tlog_path):
    imu = dict(xgyro=0, ygyro=0, zgyro=0, xmag=0, ymag=0, zmag=0)
    messages = [
        FakeMavMessage("RAW_IMU", T0, time_usec=1000, xacc=1000, yacc=0, zacc=0, **imu),
        FakeMavMessage("HIGHRES_IMU", T0, time_usec=1000, xacc=2.0, yacc=0.0, zacc=-9.8),
        FakeMavMessage("SCALED_IMU2", T0, time_boot_ms=1, xacc=0, yacc=1000, zacc=0, **imu),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    assert topics["sensor_accel"]["x"].iloc[0] == pytest.approx(2.0)  # HIGHRES_IMU wins
    assert topics["sensor_accel_1"]["y"].iloc[0] == pytest.approx(9.80665)


def test_gps_raw_int_maps_to_vehicle_gps_position(monkeypatch, tmp_tlog_path):
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, [gps_raw(T0)])

    gps = topics["vehicle_gps_position"]
    assert gps["lat"].iloc[0] == 377749000
    assert gps["fix_type"].iloc[0] == 3
    assert gps["satellites_used"].iloc[0] == 11
    assert gps["hdop"].iloc[0] == pytest.approx(1.5)
    assert "jamming_indicator" not in gps.columns


def test_unknown_satellite_count_is_nan(monkeypatch, tmp_tlog_path):
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, [gps_raw(T0, fix=0, sats=255, lat=0, lon=0)])
    assert np.isnan(topics["vehicle_gps_position"]["satellites_used"].iloc[0])


def test_global_position_int_kept_out_of_gps_topic(monkeypatch, tmp_tlog_path):
    # the QGC tlog case that crashed the GPS analyser: GLOBAL_POSITION_INT rows have no fix_type
    messages = []
    for k in range(5):
        messages.append(gps_raw(T0 + k))
        messages.append(FakeMavMessage("GLOBAL_POSITION_INT", T0 + k + 0.5, time_boot_ms=1000 * k + 500,
                                       lat=377749000, lon=-1224194000, alt=100000, relative_alt=30000,
                                       vx=0, vy=0, vz=0, hdg=0))
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    gps = topics["vehicle_gps_position"]
    assert len(gps) == 5
    assert gps["fix_type"].notna().all()
    assert gps["fix_type"].dtype == np.int64

    gpos = topics["vehicle_global_position"]
    assert gpos["lat"].iloc[0] == pytest.approx(37.7749)
    assert gpos["alt"].iloc[0] == pytest.approx(100.0)


def test_global_position_only_gives_no_gps_topic(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("GLOBAL_POSITION_INT", T0, time_boot_ms=0, lat=377749000, lon=-1224194000,
                       alt=100000, relative_alt=0, vx=0, vy=0, vz=0, hdg=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert "vehicle_gps_position" not in topics
    assert "vehicle_global_position" in topics


def test_sys_status_maps_to_battery_status(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("SYS_STATUS", T0,
                       onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
                       onboard_control_sensors_health=0, load=500, voltage_battery=16800,
                       current_battery=2000, battery_remaining=80, drop_rate_comm=0, errors_comm=0,
                       errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    bat = topics["battery_status"]
    assert bat["voltage_v"].iloc[0] == pytest.approx(16.8)
    assert bat["current_a"].iloc[0] == pytest.approx(20.0)
    assert bat["remaining"].iloc[0] == pytest.approx(0.8)


def battery_status(t, voltages, current=1500, bid=0):
    return FakeMavMessage("BATTERY_STATUS", t, id=bid, battery_function=0, type=0, temperature=2500,
                          voltages=voltages, current_battery=current, current_consumed=120,
                          energy_consumed=-1, battery_remaining=70)


def test_battery_status_preferred_over_sys_status(monkeypatch, tmp_tlog_path):
    cells = [4200, 4200, 4200, 4200] + [65535] * 6
    messages = []
    for k in range(3):
        messages.append(battery_status(T0 + k, cells))
        messages.append(FakeMavMessage("SYS_STATUS", T0 + k + 0.5, voltage_battery=16000,
                                       current_battery=-1, battery_remaining=-1))
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    bat = topics["battery_status"]
    assert len(bat) == 3
    assert bat["voltage_v"].tolist() == pytest.approx([16.8] * 3)
    assert bat["temperature"].iloc[0] == pytest.approx(25.0)
    assert bat["current_consumed_mah"].iloc[0] == 120


def test_battery_status_unmeasured_sentinels_treated_as_missing(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("BATTERY_STATUS", T0, id=0, battery_function=0, type=0,
                       temperature=32767, voltages=[65535] * 10, current_battery=-1,
                       current_consumed=-1, energy_consumed=-1, battery_remaining=-1),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert "battery_status" not in topics


def test_arming_from_heartbeat(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0, armed=False),
        heartbeat(T0 + 1, armed=True),
        heartbeat(T0 + 2, armed=True),
        heartbeat(T0 + 3, armed=False),
        heartbeat(T0 + 4, armed=True),
    ]
    topics, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)

    assert topics["vehicle_status"]["arming_state"].tolist() == [1, 2, 2, 1, 2]
    assert metadata.arm_count == 2


def test_px4_custom_mode_to_nav_state(monkeypatch, tmp_tlog_path):
    posctl = 3 << 16
    mission = (4 << 16) | (4 << 24)
    messages = [
        heartbeat(T0, autopilot=12, custom_mode=posctl),
        heartbeat(T0 + 1, autopilot=12, custom_mode=mission),
    ]
    topics, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)

    assert topics["vehicle_status"]["nav_state"].tolist() == [2, 3]
    assert metadata.flight_modes_used == ["Auto Mission", "Position Control"]


def test_ardupilot_mode_to_nav_state(monkeypatch, tmp_tlog_path):
    topics, _, metadata = parse(monkeypatch, tmp_tlog_path, [heartbeat(T0, custom_mode=5)])  # copter LOITER
    assert topics["vehicle_status"]["nav_state"].tolist() == [2]
    assert metadata.flight_modes_used == ["LOITER"]
    assert metadata.vehicle_type == "Copter"


def test_other_systems_ignored(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0),
        heartbeat(T0, armed=False, autopilot=8, mav_type=6, sys_id=255, comp=190),  # the GCS
        attitude(T0, 0, 0.1),
        attitude(T0, 0, 9.9, sys_id=2),  # another vehicle on the same link
        attitude(T0, 0, 9.9, comp=154),  # gimbal
    ]
    topics, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)

    assert topics["vehicle_angular_velocity"]["rollspeed"].tolist() == [0.1]
    assert topics["vehicle_status"]["arming_state"].tolist() == [2]
    assert any("other systems" in w for w in metadata.parse_warnings)


def test_landed_state(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("EXTENDED_SYS_STATE", T0, vtol_state=0, landed_state=1),
        FakeMavMessage("EXTENDED_SYS_STATE", T0 + 1, vtol_state=0, landed_state=2),
        FakeMavMessage("EXTENDED_SYS_STATE", T0 + 2, vtol_state=0, landed_state=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert topics["vehicle_land_detected"]["landed"].tolist() == [True, False]


def test_px4_int_params_decoded_bytewise(monkeypatch, tmp_tlog_path):
    as_float = struct.unpack("<f", struct.pack("<i", 4001))[0]
    messages = [
        heartbeat(T0, autopilot=12),
        FakeMavMessage("PARAM_VALUE", T0, param_id="SYS_AUTOSTART", param_value=as_float,
                       param_type=6, param_count=2, param_index=0),
        FakeMavMessage("PARAM_VALUE", T0, param_id=b"MC_ROLLRATE_P\x00\x00\x00", param_value=0.15,
                       param_type=9, param_count=2, param_index=1),
    ]
    _, params, _ = parse(monkeypatch, tmp_tlog_path, messages)

    assert params["SYS_AUTOSTART"] == 4001
    assert params["MC_ROLLRATE_P"] == pytest.approx(0.15)


def test_ardupilot_int_params_are_plain_floats(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0, autopilot=3),
        FakeMavMessage("PARAM_VALUE", T0, param_id="FRAME_CLASS", param_value=1.0,
                       param_type=2, param_count=1, param_index=0),
    ]
    _, params, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert params["FRAME_CLASS"] == 1.0


def test_bad_data_reported(monkeypatch, tmp_tlog_path):
    messages = [FakeMavMessage("BAD_DATA", T0), FakeMavMessage("BAD_DATA", T0), attitude(T0, 0)]
    _, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)
    assert any(w.startswith("2 unreadable") for w in metadata.parse_warnings)


def test_log_start_from_receive_clock(monkeypatch, tmp_tlog_path):
    _, _, metadata = parse(monkeypatch, tmp_tlog_path, [heartbeat(T0), attitude(T0 + 1, 1000)])
    assert metadata.log_start_utc == "2023-11-14T22:13:20Z"


def test_estimator_status_not_synthesized(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("EKF_STATUS_REPORT", T0, flags=3, velocity_variance=0.1, pos_horiz_variance=0.1,
                       pos_vert_variance=0.1, compass_variance=0.1, terrain_alt_variance=0.1),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert "estimator_status" not in topics


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        MavlinkTelemetryParser().parse("/no/such/file.tlog")
