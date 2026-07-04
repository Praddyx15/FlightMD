"""
Tests for ArduPilotBinParser's field-mapping logic.

No real ArduPilot .bin sample file is available in this repo (see
tests/sample_logs/README.md), so pymavlink's DFReader is mocked with
synthetic messages that mirror real ArduPilot dataflash field names. This
exercises the mapping logic directly rather than testing DFReader itself.
"""

import pytest

from flightmd_core.services.ardupilot_parser import ArduPilotBinParser


class FakeDFMessage:
    def __init__(self, mtype: str, timestamp: float, **fields):
        self._mtype = mtype
        self._timestamp = timestamp
        self._fields = fields

    def get_type(self) -> str:
        return self._mtype

    def to_dict(self) -> dict:
        return dict(self._fields)


class FakeDFReader:
    def __init__(self, messages: list[FakeDFMessage], params: dict):
        self._messages = iter(messages)
        self.params = params

    def recv_msg(self):
        return next(self._messages, None)


@pytest.fixture
def tmp_bin_path(tmp_path):
    p = tmp_path / "flight.bin"
    p.write_bytes(b"\xA3\x95")  # just needs to exist; content is irrelevant, DFReader is mocked
    return str(p)


def _patch_dfreader(monkeypatch, messages, params=None):
    fake_reader = FakeDFReader(messages, params or {})

    def fake_binary(*args, **kwargs):
        return fake_reader

    from pymavlink import DFReader
    monkeypatch.setattr(DFReader, "DFReader_binary", fake_binary)


def test_imu_maps_to_gyro_and_accel_topics(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("IMU", 1000.0, I=0, GyrX=0.1, GyrY=0.2, GyrZ=0.3,
                      AccX=1.0, AccY=2.0, AccZ=9.8),
        FakeDFMessage("IMU", 1000.1, I=0, GyrX=0.15, GyrY=0.25, GyrZ=0.35,
                      AccX=1.1, AccY=2.1, AccZ=9.9),
    ]
    _patch_dfreader(monkeypatch, messages)

    topics, params, metadata = ArduPilotBinParser().parse(tmp_bin_path)

    assert "vehicle_angular_velocity" in topics
    gyro = topics["vehicle_angular_velocity"]
    assert list(gyro["rollspeed"]) == pytest.approx([0.1, 0.15])
    assert list(gyro["pitchspeed"]) == pytest.approx([0.2, 0.25])
    assert list(gyro["yawspeed"]) == pytest.approx([0.3, 0.35])

    assert "sensor_accel_0" in topics
    accel = topics["sensor_accel_0"]
    assert list(accel["x"]) == pytest.approx([1.0, 1.1])
    assert list(accel["z"]) == pytest.approx([9.8, 9.9])


def test_bat_maps_to_battery_status(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("BAT", 1000.0, Volt=16.8, Curr=2.0, Temp=25.0, CurrTot=0),
        FakeDFMessage("BAT", 1010.0, Volt=15.5, Curr=20.0, Temp=30.0, CurrTot=500),
    ]
    _patch_dfreader(monkeypatch, messages, params={"BATT_CAPACITY": 5000})

    topics, params, metadata = ArduPilotBinParser().parse(tmp_bin_path)

    assert "battery_status" in topics
    bat = topics["battery_status"]
    assert list(bat["voltage_v"]) == pytest.approx([16.8, 15.5])
    assert list(bat["current_a"]) == pytest.approx([2.0, 20.0])
    assert list(bat["temperature"]) == pytest.approx([25.0, 30.0])
    # remaining is derived from CurrTot / rated capacity
    assert bat["remaining"].iloc[0] == pytest.approx(1.0)
    assert bat["remaining"].iloc[1] == pytest.approx(1.0 - 500 / 5000)


def test_gps_lat_lon_scaled_to_px4_fixed_point(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, Lat=37.7749, Lng=-122.4194, Alt=100.0,
                       NSats=12, HDop=0.9, Status=3),
    ]
    _patch_dfreader(monkeypatch, messages)

    topics, params, metadata = ArduPilotBinParser().parse(tmp_bin_path)

    assert "vehicle_gps_position" in topics
    gps = topics["vehicle_gps_position"]
    # PX4 convention: lat/lon as int32 degrees*1e7, alt in mm
    assert gps["lat"].iloc[0] == pytest.approx(377749000, abs=10)
    assert gps["lon"].iloc[0] == pytest.approx(-1224194000, abs=10)
    assert gps["alt"].iloc[0] == pytest.approx(100000.0)
    assert gps["satellites_used"].iloc[0] == 12
    # No jamming/spoofing equivalent exists in ArduPilot dataflash logs
    assert "jamming_indicator" not in gps.columns
    assert "spoofing_state" not in gps.columns


def test_estimator_status_not_synthesized(monkeypatch, tmp_bin_path):
    """
    EKF3/XKF bit semantics are not confidently mappable to PX4's
    innovation_check_flags / solution_status_flags without verification
    against a real log — this parser must never fabricate that topic.
    """
    messages = [
        FakeDFMessage("GPS", 1000.0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0, Status=3),
    ]
    _patch_dfreader(monkeypatch, messages)

    topics, params, metadata = ArduPilotBinParser().parse(tmp_bin_path)

    assert "estimator_status" not in topics


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ArduPilotBinParser().parse("/no/such/file.bin")
