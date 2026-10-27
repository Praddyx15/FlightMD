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


def esc_status(t, index, rpm, boot_us):
    return FakeMavMessage("ESC_STATUS", t, index=index, time_usec=boot_us, rpm=rpm,
                          voltage=[16.0] * 4, current=[5.0] * 4)


def esc_info(t, index, count, temps, boot_us):
    return FakeMavMessage("ESC_INFO", t, index=index, time_usec=boot_us, counter=0, count=count,
                          connection_type=0, info=0, failure_flags=[0] * 4, error_count=[0] * 4,
                          temperature=temps)


def test_esc_status_trimmed_to_esc_info_count(monkeypatch, tmp_tlog_path):
    messages = [heartbeat(T0, autopilot=12)]
    for k in range(5):
        boot = 1_000_000 + k * 100_000
        messages.append(esc_status(T0 + k * 0.1, 0, [4000, 4010, 4020, 4030], boot))
        messages.append(esc_status(T0 + k * 0.1, 4, [3900, 3910, 0, 0], boot))
        messages.append(esc_info(T0 + k * 0.1, 0, 6, [4500, 4600, 4700, 4800], boot))
        messages.append(esc_info(T0 + k * 0.1, 4, 6, [4900, 5000, 32767, 32767], boot))
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    esc = topics["esc_status"]
    assert (esc["esc_count"] == 6).all()
    assert "esc[5].esc_rpm" in esc.columns
    assert "esc[6].esc_rpm" not in esc.columns
    assert esc["esc[1].esc_rpm"].iloc[-1] == 4010
    assert esc["esc[0].esc_temperature"].iloc[-1] == pytest.approx(45.0)


def test_ardupilot_esc_telemetry_without_count(monkeypatch, tmp_tlog_path):
    messages = [heartbeat(T0)]
    for k in range(5):
        messages.append(FakeMavMessage(
            "ESC_TELEMETRY_1_TO_4", T0 + k * 0.1, temperature=[40, 41, 42, 43],
            voltage=[1600] * 4, current=[500, 510, 520, 530], totalcurrent=[0] * 4,
            rpm=[4000, 4100, 4200, 4300], count=[k] * 4))
        messages.append(FakeMavMessage(
            "ESC_TELEMETRY_5_TO_8", T0 + k * 0.1, temperature=[0] * 4, voltage=[0] * 4,
            current=[0] * 4, totalcurrent=[0] * 4, rpm=[0] * 4, count=[0] * 4))
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)

    esc = topics["esc_status"]
    assert (esc["esc_count"] == 4).all()
    assert esc["esc[3].esc_rpm"].iloc[0] == 4300
    assert esc["esc[0].esc_voltage"].iloc[0] == pytest.approx(16.0)
    assert esc["esc[1].esc_current"].iloc[0] == pytest.approx(5.1)
    assert esc["esc[2].esc_temperature"].iloc[0] == 42
    assert not any(c.startswith("esc[4]") for c in esc.columns)


def vibration(t, boot_us, x=1.0, y=2.0, z=3.0, clips=(0, 0, 0)):
    return FakeMavMessage("VIBRATION", t, time_usec=boot_us, vibration_x=x, vibration_y=y,
                          vibration_z=z, clipping_0=clips[0], clipping_1=clips[1], clipping_2=clips[2])


def test_ardupilot_vibration_topic(monkeypatch, tmp_tlog_path):
    messages = [heartbeat(T0), vibration(T0, 1_000_000, clips=(5, 0, 0)),
                vibration(T0 + 1, 2_000_000, clips=(7, 0, 0))]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    vib = topics["vibration"]
    assert vib["vibration_z"].tolist() == [3.0, 3.0]
    assert vib["clipping_0"].tolist() == [5, 7]
    assert "vehicle_imu_status" not in topics


def test_px4_vibration_goes_to_vehicle_imu_status(monkeypatch, tmp_tlog_path):
    messages = [heartbeat(T0, autopilot=12), vibration(T0, 1_000_000, x=0.01, y=0.02, z=4.5)]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    imu = topics["vehicle_imu_status"]
    assert imu["accel_vibration_metric"].iloc[0] == pytest.approx(4.5)
    assert imu["gyro_vibration_metric"].iloc[0] == pytest.approx(0.02)
    assert imu["delta_angle_coning_metric"].iloc[0] == pytest.approx(0.01)
    assert "vibration" not in topics


def test_ekf_status_report_squared_to_test_ratios(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0),
        FakeMavMessage("EKF_STATUS_REPORT", T0, flags=831, velocity_variance=0.5, pos_horiz_variance=0.3,
                       pos_vert_variance=0.2, compass_variance=0.1, terrain_alt_variance=0.0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    ekf = topics["ekf_test_ratios"]
    assert ekf["vel_test_ratio"].iloc[0] == pytest.approx(0.25)
    assert ekf["pos_test_ratio"].iloc[0] == pytest.approx(0.09)
    assert ekf["flags"].iloc[0] == 831
    assert "tas_test_ratio" not in ekf.columns


def test_px4_estimator_status_ratios_kept_as_is(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0, autopilot=12),
        FakeMavMessage("ESTIMATOR_STATUS", T0, time_usec=1_000_000, flags=0, vel_ratio=0.5,
                       pos_horiz_ratio=0.3, pos_vert_ratio=0.2, mag_ratio=0.1, hagl_ratio=0.0,
                       tas_ratio=0.0, pos_horiz_accuracy=0.5, pos_vert_accuracy=0.8),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert topics["ekf_test_ratios"]["vel_test_ratio"].iloc[0] == pytest.approx(0.5)
    assert "estimator_status" not in topics


def test_battery_cells(monkeypatch, tmp_tlog_path):
    cells = [3900, 3910, 3920, 3930, 3940, 3950] + [65535] * 4
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, [battery_status(T0, cells)])
    bat = topics["battery_status"]
    assert bat["cell_count"].iloc[0] == 6
    assert bat["voltage_cell_v[5]"].iloc[0] == pytest.approx(3.95)
    assert "voltage_cell_v[6]" not in bat.columns
    assert bat["voltage_v"].iloc[0] == pytest.approx(23.55)


def test_firmware_board_and_airframe_ardupilot(monkeypatch, tmp_tlog_path):
    messages = [
        heartbeat(T0),
        FakeMavMessage("STATUSTEXT", T0, severity=6, text="ArduCopter V4.5.7 (2a3dc4b7)"),
        FakeMavMessage("STATUSTEXT", T0, severity=6, text=b"CubeOrange 0035002A 30395112 34313234\x00\x00"),
        # the GCS's own text isn't the vehicle's
        FakeMavMessage("STATUSTEXT", T0, severity=6, text="Frame: QUAD/X", sys_id=255),
        FakeMavMessage("PARAM_VALUE", T0, param_id="FRAME_CLASS", param_value=2.0, param_type=2),
        FakeMavMessage("PARAM_VALUE", T0, param_id="FRAME_TYPE", param_value=0.0, param_type=2),
    ]
    _, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)
    assert metadata.firmware_version == "ArduCopter V4.5.7 (2a3dc4b7)"
    assert metadata.hardware_id == "CubeOrange"
    assert metadata.airframe_name == "Hexa Plus"
    assert metadata.px4_version is None


def test_px4_firmware_from_autopilot_version(monkeypatch, tmp_tlog_path):
    as_float = struct.unpack("<f", struct.pack("<i", 4001))[0]
    messages = [
        heartbeat(T0, autopilot=12),
        FakeMavMessage("AUTOPILOT_VERSION", T0, capabilities=0, flight_sw_version=0x010E03FF,
                       middleware_sw_version=0, os_sw_version=0, board_version=0),
        FakeMavMessage("PARAM_VALUE", T0, param_id="SYS_AUTOSTART", param_value=as_float, param_type=6),
    ]
    _, _, metadata = parse(monkeypatch, tmp_tlog_path, messages)
    assert metadata.px4_version == "v1.14.3"
    assert metadata.firmware_version == "PX4 v1.14.3"
    assert metadata.airframe_id == 4001
    assert metadata.airframe_name == "Generic Quadcopter"


def test_attitude_quaternion_rates_used_without_attitude(monkeypatch, tmp_tlog_path):
    messages = [FakeMavMessage("ATTITUDE_QUATERNION", T0, time_boot_ms=0, q1=1, q2=0, q3=0, q4=0,
                               rollspeed=0.4, pitchspeed=0.5, yawspeed=0.6)]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert topics["vehicle_angular_velocity"]["rollspeed"].iloc[0] == pytest.approx(0.4)


def test_attitude_wins_over_attitude_quaternion(monkeypatch, tmp_tlog_path):
    messages = [
        attitude(T0, 0, 0.1),
        FakeMavMessage("ATTITUDE_QUATERNION", T0, time_boot_ms=0, q1=1, q2=0, q3=0, q4=0,
                       rollspeed=0.4, pitchspeed=0.5, yawspeed=0.6),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    assert topics["vehicle_angular_velocity"]["rollspeed"].tolist() == [0.1]


def test_power_status_preferred_over_hwstatus(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("POWER_STATUS", T0, Vcc=5050, Vservo=5200, flags=1),
        FakeMavMessage("HWSTATUS", T0, Vcc=4900, I2Cerr=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_tlog_path, messages)
    power = topics["system_power"]
    assert power["voltage5v_v"].tolist() == [pytest.approx(5.05)]
    assert power["servo_rail_v"].iloc[0] == pytest.approx(5.2)
    assert power["power_flags"].iloc[0] == 1


def test_progress_from_reader_percent(monkeypatch, tmp_tlog_path):
    from pymavlink import mavutil
    from flightmd_core.services import mavlink_telemetry_parser

    monkeypatch.setattr(mavlink_telemetry_parser, "PROGRESS_EVERY", 1)
    conn = FakeMavConnection([attitude(T0, 0), attitude(T0 + 1, 1000)])
    conn.percent = 40.0
    monkeypatch.setattr(mavutil, "mavlogfile", lambda *a, **k: conn)
    seen = []
    MavlinkTelemetryParser().parse(tmp_tlog_path, progress=seen.append)
    assert seen == [pytest.approx(0.4), pytest.approx(0.4)]
