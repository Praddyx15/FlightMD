"""
Tests for MavlinkTelemetryParser's field-mapping logic.

pymavlink's mavutil.mavlink_connection is mocked with synthetic messages
matching real MAVLink field names (verified via direct introspection of the
installed pymavlink dialect — see mavlink_telemetry_parser.py comments) so
the mapping logic is exercised without needing a real .tlog sample.
"""

import pytest

from flightmd_core.services.mavlink_telemetry_parser import MavlinkTelemetryParser


class FakeMavMessage:
    def __init__(self, mtype: str, timestamp: float, **fields):
        self._mtype = mtype
        self._timestamp = timestamp
        for k, v in fields.items():
            setattr(self, k, v)

    def get_type(self) -> str:
        return self._mtype


class FakeMavConnection:
    def __init__(self, messages: list[FakeMavMessage]):
        self._messages = iter(messages)
        self.closed = False

    def recv_match(self, blocking=False):
        return next(self._messages, None)

    def close(self):
        self.closed = True


@pytest.fixture
def tmp_tlog_path(tmp_path):
    p = tmp_path / "flight.tlog"
    p.write_bytes(b"\xfd\x00")  # just needs to exist; content is irrelevant, connection is mocked
    return str(p)


def _patch_connection(monkeypatch, messages):
    fake_conn = FakeMavConnection(messages)

    def fake_mavlink_connection(*args, **kwargs):
        return fake_conn

    from pymavlink import mavutil
    monkeypatch.setattr(mavutil, "mavlink_connection", fake_mavlink_connection)
    return fake_conn


def test_attitude_maps_to_angular_velocity(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("ATTITUDE", 1000.0, time_boot_ms=0,
                        roll=0.0, pitch=0.0, yaw=0.0,
                        rollspeed=0.1, pitchspeed=0.2, yawspeed=0.3),
        FakeMavMessage("ATTITUDE", 1000.1, time_boot_ms=100,
                        roll=0.0, pitch=0.0, yaw=0.0,
                        rollspeed=0.15, pitchspeed=0.25, yawspeed=0.35),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    assert "vehicle_angular_velocity" in topics
    gyro = topics["vehicle_angular_velocity"]
    assert list(gyro["rollspeed"]) == pytest.approx([0.1, 0.15])
    assert list(gyro["yawspeed"]) == pytest.approx([0.3, 0.35])


def test_raw_imu_accel_converted_to_ms2(monkeypatch, tmp_tlog_path):
    # xacc/yacc/zacc are in mG; 1000 mG = 9.80665 m/s^2
    messages = [
        FakeMavMessage("RAW_IMU", 1000.0, time_usec=0,
                        xacc=0, yacc=0, zacc=1000,
                        xgyro=0, ygyro=0, zgyro=0,
                        xmag=0, ymag=0, zmag=0),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    assert "sensor_accel_0" in topics
    accel = topics["sensor_accel_0"]
    assert accel["z"].iloc[0] == pytest.approx(9.80665)


def test_gps_raw_int_maps_to_vehicle_gps_position(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("GPS_RAW_INT", 1000.0, time_usec=0,
                        fix_type=3, lat=377749000, lon=-1224194000, alt=100000,
                        eph=150, epv=200, vel=500, cog=0, satellites_visible=11),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    assert "vehicle_gps_position" in topics
    gps = topics["vehicle_gps_position"]
    assert gps["lat"].iloc[0] == 377749000
    assert gps["fix_type"].iloc[0] == 3
    assert gps["satellites_used"].iloc[0] == 11
    assert gps["hdop"].iloc[0] == pytest.approx(1.5)
    # No jamming/spoofing equivalent in standard MAVLink telemetry
    assert "jamming_indicator" not in gps.columns


def test_sys_status_maps_to_battery_status(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("SYS_STATUS", 1000.0,
                        onboard_control_sensors_present=0,
                        onboard_control_sensors_enabled=0,
                        onboard_control_sensors_health=0,
                        load=500, voltage_battery=16800, current_battery=2000,
                        battery_remaining=80,
                        drop_rate_comm=0, errors_comm=0,
                        errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    assert "battery_status" in topics
    bat = topics["battery_status"]
    assert bat["voltage_v"].iloc[0] == pytest.approx(16.8)
    assert bat["current_a"].iloc[0] == pytest.approx(20.0)
    assert bat["remaining"].iloc[0] == pytest.approx(0.8)


def test_battery_status_unmeasured_sentinels_treated_as_missing(monkeypatch, tmp_tlog_path):
    messages = [
        FakeMavMessage("BATTERY_STATUS", 1000.0,
                        id=0, battery_function=0, type=0,
                        temperature=32767,  # INT16_MAX sentinel = "not measured"
                        voltages=[65535] * 10,
                        current_battery=-1,  # sentinel = "not measured"
                        current_consumed=-1, energy_consumed=-1,
                        battery_remaining=-1),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    # All fields were sentinel/unmeasured — no usable battery data, so the
    # topic should not be fabricated with meaningless zeros.
    assert "battery_status" not in topics


def test_estimator_status_not_synthesized(monkeypatch, tmp_tlog_path):
    """
    EKF_STATUS_REPORT.flags uses the ESTIMATOR_STATUS_FLAGS enum, which does
    not map cleanly onto all bits of PX4's solution_status_flags (no
    equivalent to PX4's gps_available bit) — this parser must never
    fabricate that topic from a partial/guessed mapping.
    """
    messages = [
        FakeMavMessage("EKF_STATUS_REPORT", 1000.0,
                        flags=3, velocity_variance=0.1, pos_horiz_variance=0.1,
                        pos_vert_variance=0.1, compass_variance=0.1, terrain_alt_variance=0.1),
    ]
    _patch_connection(monkeypatch, messages)

    topics, params, metadata = MavlinkTelemetryParser().parse(tmp_tlog_path)

    assert "estimator_status" not in topics


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        MavlinkTelemetryParser().parse("/no/such/file.tlog")
