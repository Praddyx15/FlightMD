"""
ArduPilotBinParser field mapping, with pymavlink's DFReader replaced by fake messages
that use real dataflash field names. tests/test_sample_logs.py runs the real DFReader.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from flightmd_core.services.ardupilot_parser import ArduPilotBinParser


class FakeDFMessage:
    def __init__(self, mtype: str, timestamp: float, **fields):
        self._mtype = mtype
        self._fields = {"TimeUS": int(round(timestamp * 1e6)), **fields}

    def get_type(self) -> str:
        return self._mtype

    def to_dict(self) -> dict:
        return dict(self._fields)


class FakeDFReader:
    def __init__(self, messages, params):
        self._messages = iter(messages)
        self.params = params

    def recv_match(self, type=None):
        for m in self._messages:
            if type is None or m.get_type() in type:
                return m
        return None


@pytest.fixture
def tmp_bin_path(tmp_path):
    p = tmp_path / "flight.bin"
    p.write_bytes(b"\xA3\x95")  # only has to exist, DFReader is faked
    return str(p)


def parse(monkeypatch, path, messages, params=None):
    from pymavlink import DFReader
    reader = FakeDFReader(messages, params or {})
    monkeypatch.setattr(DFReader, "DFReader_binary", lambda *a, **k: reader)
    return ArduPilotBinParser().parse(path)


def test_imu_maps_to_gyro_and_accel_topics(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("IMU", 1000.0, I=0, GyrX=0.1, GyrY=0.2, GyrZ=0.3, AccX=1.0, AccY=2.0, AccZ=9.8),
        FakeDFMessage("IMU", 1000.1, I=0, GyrX=0.15, GyrY=0.25, GyrZ=0.35, AccX=1.1, AccY=2.1, AccZ=9.9),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    gyro = topics["vehicle_angular_velocity"]
    assert list(gyro["rollspeed"]) == pytest.approx([0.1, 0.15])
    assert list(gyro["pitchspeed"]) == pytest.approx([0.2, 0.25])
    assert list(gyro["yawspeed"]) == pytest.approx([0.3, 0.35])

    accel = topics["sensor_accel"]
    assert list(accel["x"]) == pytest.approx([1.0, 1.1])
    assert list(accel["z"]) == pytest.approx([9.8, 9.9])
    # log-relative microseconds
    assert list(accel["timestamp"]) == [0, 100_000]


def test_imu_instances_are_not_duplicated(monkeypatch, tmp_bin_path):
    messages = []
    for k in range(3):
        t = 10.0 + k * 0.01
        messages += [
            FakeDFMessage("IMU", t, I=0, GyrX=0, GyrY=0, GyrZ=0, AccX=0, AccY=0, AccZ=-9.8),
            FakeDFMessage("IMU", t, I=1, GyrX=0, GyrY=0, GyrZ=0, AccX=1, AccY=1, AccZ=-9.8),
        ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    accel_keys = sorted(k for k in topics if k.startswith("sensor_accel"))
    assert accel_keys == ["sensor_accel", "sensor_accel_1"]
    assert list(topics["sensor_accel"]["x"]) == [0, 0, 0]
    assert list(topics["sensor_accel_1"]["x"]) == [1, 1, 1]


def test_pre_4_0_imu2_messages_are_their_own_instance(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("IMU", 10.0, GyrX=0, GyrY=0, GyrZ=0, AccX=0, AccY=0, AccZ=-9.8),
        FakeDFMessage("IMU2", 10.0, GyrX=0, GyrY=0, GyrZ=0, AccX=5, AccY=0, AccZ=-9.8),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    assert topics["sensor_accel"]["x"].iloc[0] == 0
    assert topics["sensor_accel_1"]["x"].iloc[0] == 5


def test_bat_maps_to_battery_status(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("BAT", 1000.0, Inst=0, Volt=16.8, Curr=2.0, Temp=25.0, CurrTot=0),
        FakeDFMessage("BAT", 1010.0, Inst=0, Volt=15.5, Curr=20.0, Temp=30.0, CurrTot=500),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages, params={"BATT_CAPACITY": 5000})

    bat = topics["battery_status"]
    assert list(bat["voltage_v"]) == pytest.approx([16.8, 15.5])
    assert list(bat["current_a"]) == pytest.approx([2.0, 20.0])
    assert list(bat["temperature"]) == pytest.approx([25.0, 30.0])
    assert list(bat["current_consumed_mah"]) == pytest.approx([0, 500])
    assert (bat["capacity"] == 5000).all()
    # not derived from CurrTot / capacity: that made the capacity-fade check circular
    assert "remaining" not in bat.columns


def test_bat_remaining_from_rempct(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("BAT", 1000.0, Inst=0, Volt=16.8, Curr=2.0, RemPct=87)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    assert topics["battery_status"]["remaining"].iloc[0] == pytest.approx(0.87)


def test_second_battery_kept_separate(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("BAT", 1000.0, Inst=0, Volt=16.8, Curr=2.0),
        FakeDFMessage("BAT", 1000.0, Inst=1, Volt=25.2, Curr=1.0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    assert topics["battery_status"]["voltage_v"].iloc[0] == pytest.approx(16.8)
    assert topics["battery_status_1"]["voltage_v"].iloc[0] == pytest.approx(25.2)


def test_gps_lat_lon_scaled_to_px4_fixed_point(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, I=0, Lat=37.7749, Lng=-122.4194, Alt=100.0, NSats=12, HDop=0.9, Status=3),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    gps = topics["vehicle_gps_position"]
    assert gps["lat"].iloc[0] == pytest.approx(377749000, abs=10)
    assert gps["lon"].iloc[0] == pytest.approx(-1224194000, abs=10)
    assert gps["alt"].iloc[0] == pytest.approx(100000.0)
    assert gps["satellites_used"].iloc[0] == 12
    assert gps["fix_type"].dtype == np.int64
    assert "jamming_indicator" not in gps.columns
    assert "spoofing_state" not in gps.columns


def test_gps_receivers_not_interleaved(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, I=0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=14, HDop=0.8, Status=3),
        FakeDFMessage("GPS", 1000.0, I=1, Lat=1.0, Lng=1.0, Alt=1.0, NSats=6, HDop=2.0, Status=3),
        FakeDFMessage("GPS2", 1000.2, Lat=1.0, Lng=1.0, Alt=1.0, NSats=6, HDop=2.0, Status=3),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    assert list(topics["vehicle_gps_position"]["satellites_used"]) == [14]
    assert list(topics["vehicle_gps_position_1"]["satellites_used"]) == [6, 6]


def test_gps_rows_without_status_dropped(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0),
        FakeDFMessage("GPS", 1000.2, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0, Status=3),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    gps = topics["vehicle_gps_position"]
    assert len(gps) == 1
    assert gps["fix_type"].notna().all()


def test_log_start_utc_from_gps_week(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("IMU", 100.0, I=0, GyrX=0, GyrY=0, GyrZ=0, AccX=0, AccY=0, AccZ=-9.8),
        FakeDFMessage("GPS", 110.0, I=0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0, Status=3,
                      GWk=2300, GMS=345_600_000),
    ]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages)

    gps_time = datetime(1980, 1, 6, tzinfo=timezone.utc) + timedelta(weeks=2300, milliseconds=345_600_000)
    # GPS runs 18 s ahead of UTC; the log started 10 s before the GPS row
    expected = gps_time - timedelta(seconds=18) - timedelta(seconds=10)
    assert metadata.log_start_utc == expected.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_esc_instances_binned_onto_one_time_base(monkeypatch, tmp_bin_path):
    # four ESCs at 10 Hz, each a few ms after the previous one, like a real ArduCopter log
    messages = []
    for k in range(20):
        for i in range(4):
            messages.append(FakeDFMessage(
                "ESC", 50.0 + k * 0.1 + i * 0.004,
                Instance=i, RPM=4000.0 + i, Volt=16.0, Curr=5.0, Temp=40.0,
            ))
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    esc = topics["esc_status"]
    assert len(esc) == 20  # one row per sample time, not 80 mostly-empty rows
    assert (esc["esc_count"] == 4).all()
    for i in range(4):
        assert (esc[f"esc[{i}].esc_rpm"] == 4000.0 + i).all()
    assert not (esc.filter(like="esc_rpm") == 0).any().any()


def test_esc_missing_values_stay_nan(monkeypatch, tmp_bin_path):
    messages = []
    for k in range(10):
        messages.append(FakeDFMessage("ESC", 50.0 + k * 0.1, Instance=0, RPM=4000.0, Volt=16.0, Curr=5.0))
        if k != 4:
            messages.append(FakeDFMessage("ESC", 50.002 + k * 0.1, Instance=1, RPM=4100.0, Volt=16.0, Curr=5.0))
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    rpm1 = topics["esc_status"]["esc[1].esc_rpm"]
    assert rpm1.isna().sum() == 1
    assert (rpm1.dropna() == 4100.0).all()
    assert topics["esc_status"]["esc[0].esc_temperature"].isna().all()


def test_esc_rows_start_once_every_esc_reported(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("ESC", 50.0 + k * 0.1, Instance=0, RPM=1.0) for k in range(10)]
    messages += [FakeDFMessage("ESC", 50.5 + k * 0.1, Instance=1, RPM=2.0) for k in range(5)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, sorted(messages, key=lambda m: m._fields["TimeUS"]))

    esc = topics["esc_status"]
    assert len(esc) == 5
    assert esc["esc[1].esc_rpm"].notna().all()


def test_old_numbered_esc_messages(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("ESC1", 50.0, RPM=100.0),
        FakeDFMessage("ESC2", 50.001, RPM=200.0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    esc = topics["esc_status"]
    assert esc["esc[0].esc_rpm"].iloc[0] == 100.0
    assert esc["esc[1].esc_rpm"].iloc[0] == 200.0
    assert esc["esc_count"].iloc[0] == 2


def test_arming_from_ev_events(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("MODE", 100.0, Mode=0, ModeNum=0),
        FakeDFMessage("EV", 105.0, Id=10),
        FakeDFMessage("EV", 160.0, Id=18),
        FakeDFMessage("EV", 161.0, Id=11),
        FakeDFMessage("EV", 170.0, Id=10),
        FakeDFMessage("EV", 180.0, Id=11),
    ]
    topics, _, metadata = parse(monkeypatch, tmp_bin_path, messages)

    status = topics["vehicle_status"]
    assert metadata.arm_count == 2
    assert status["arming_state"].iloc[0] == 1  # disarmed before the first ARMED event
    armed_at = status.loc[status["arming_state"] == 2, "timestamp"]
    assert armed_at.min() == 5_000_000
    assert topics["vehicle_land_detected"]["landed"].tolist() == [True]


def test_arm_messages_preferred_over_ev(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("ARM", 100.0, ArmState=1),
        FakeDFMessage("EV", 100.0, Id=10),
        FakeDFMessage("ARM", 150.0, ArmState=0),
        FakeDFMessage("EV", 150.0, Id=11),
    ]
    topics, _, metadata = parse(monkeypatch, tmp_bin_path, messages)

    assert metadata.arm_count == 1
    assert topics["vehicle_status"]["arming_state"].tolist() == [1, 2, 1]


def test_no_arming_state_without_arm_info(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("MODE", 100.0, Mode=3, ModeNum=3)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    assert "arming_state" not in topics["vehicle_status"].columns


def test_estimator_status_not_synthesized(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0, Status=3),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    assert "estimator_status" not in topics


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ArduPilotBinParser().parse("/no/such/file.bin")


def test_vehicle_type_derived_from_startup_message(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("MSG", 1000.0, Message="ArduCopter V4.3.5 (02ff7ea3)")]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages)

    assert metadata.firmware_version == "ArduCopter V4.3.5 (02ff7ea3)"
    assert metadata.vehicle_type == "Copter"


def test_random_status_text_is_not_the_firmware(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("MSG", 1000.0, Message="Vibration compensation ON"),
        FakeDFMessage("MSG", 1001.0, Message="ArduPlane V4.5.1 (1234abcd)"),
    ]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages)
    assert metadata.firmware_version == "ArduPlane V4.5.1 (1234abcd)"


def test_vehicle_type_none_when_no_startup_message(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 1000.0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=10, HDop=1.0, Status=3),
    ]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages)
    assert metadata.vehicle_type is None


def test_vibe_per_imu_with_clip_counters(monkeypatch, tmp_bin_path):
    messages = []
    for k in range(3):
        t = 100.0 + k * 0.1
        messages += [
            FakeDFMessage("VIBE", t, IMU=0, VibeX=5.0, VibeY=6.0, VibeZ=12.0, Clip=k),
            FakeDFMessage("VIBE", t + 0.001, IMU=1, VibeX=7.0, VibeY=8.0, VibeZ=20.0, Clip=10 + k),
        ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    vib = topics["vibration"]
    assert vib["vibration_z"].tolist() == [12.0, 12.0, 12.0]
    assert vib["clipping_0"].tolist() == [0, 1, 2]
    # IMU 1's counter rides along on the bare topic, last value before each row
    assert vib["clipping_1"].tolist()[1:] == [10, 11]
    assert topics["vibration_1"]["vibration_z"].tolist() == [20.0, 20.0, 20.0]


def test_old_vibe_clip0_to_clip2(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("VIBE", 100.0, VibeX=1.0, VibeY=2.0, VibeZ=3.0, Clip0=4, Clip1=5, Clip2=6)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    vib = topics["vibration"]
    assert (vib["clipping_0"].iloc[0], vib["clipping_1"].iloc[0], vib["clipping_2"].iloc[0]) == (4, 5, 6)
    assert "vibration_1" not in topics


def test_xkf4_test_ratios_squared_and_primary_core_on_bare_name(monkeypatch, tmp_bin_path):
    messages = []
    for k in range(4):
        t = 100.0 + k * 0.1
        messages += [
            FakeDFMessage("XKF4", t, C=0, SV=0.5, SP=0.2, SH=0.1, SM=0.3, SVT=0.0, FS=0, TS=0, SS=1023, GPS=0, PI=1),
            FakeDFMessage("XKF4", t, C=1, SV=0.9, SP=0.2, SH=0.1, SM=0.3, SVT=0.0, FS=0, TS=0, SS=1023, GPS=0, PI=1),
        ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)

    ekf = topics["ekf_test_ratios"]
    assert ekf["vel_test_ratio"].iloc[0] == pytest.approx(0.81)  # core 1, 0.9 squared
    assert ekf["pos_test_ratio"].iloc[0] == pytest.approx(0.04)
    assert ekf["solution_status"].iloc[0] == 1023
    assert topics["ekf_test_ratios_1"]["vel_test_ratio"].iloc[0] == pytest.approx(0.25)
    assert "estimator_status" not in topics


def test_nkf4_used_when_ekf2_is_active(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("NKF4", 100.0, SV=0.4, SP=0.1, SH=0.1, SM=0.1, SVT=0.0, FS=0, TS=0, SS=0, GPS=0, PI=0),
        FakeDFMessage("XKF4", 100.0, C=0, SV=0.9, SP=0.1, SH=0.1, SM=0.1, SVT=0.0, FS=0, TS=0, SS=0, GPS=0, PI=0),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages, params={"AHRS_EKF_TYPE": 2})
    assert topics["ekf_test_ratios"]["vel_test_ratio"].iloc[0] == pytest.approx(0.16)


def test_gpa_accuracy_merged_into_gps(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("GPS", 100.0, I=0, Lat=1.0, Lng=1.0, Alt=1.0, NSats=12, HDop=0.8, Status=3),
        FakeDFMessage("GPA", 100.0, I=0, VDop=1.1, HAcc=0.7, VAcc=1.2, SAcc=0.3),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    gps = topics["vehicle_gps_position"]
    assert gps["eph"].iloc[0] == pytest.approx(0.7)
    assert gps["epv"].iloc[0] == pytest.approx(1.2)
    assert gps["s_variance_m_s"].iloc[0] == pytest.approx(0.3)


def test_bcl_cells_and_battery_resistance(monkeypatch, tmp_bin_path):
    cells = {f"V{k}": (4100 if k <= 4 else 65535) for k in range(1, 13)}
    messages = [
        FakeDFMessage("BAT", 100.0, Inst=0, Volt=16.4, Curr=10.0, Res=0.012),
        FakeDFMessage("BCL", 100.0, Instance=0, Volt=16.4, **cells),
    ]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    bat = topics["battery_status"]
    assert bat["cell_count"].iloc[0] == 4
    assert bat["voltage_cell_v[0]"].iloc[0] == pytest.approx(4.1)
    assert "voltage_cell_v[4]" not in bat.columns
    assert bat["internal_resistance_estimate"].iloc[0] == pytest.approx(0.012)


def test_rate_desired_to_rates_setpoint_in_rad_s(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("RATE", 100.0, RDes=90.0, R=80.0, PDes=-45.0, P=0.0, YDes=0.0, Y=0.0)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    sp = topics["vehicle_rates_setpoint"]
    assert sp["roll"].iloc[0] == pytest.approx(np.pi / 2)
    assert sp["pitch"].iloc[0] == pytest.approx(-np.pi / 4)


def test_powr_to_system_power(monkeypatch, tmp_bin_path):
    messages = [FakeDFMessage("POWR", 100.0, Vcc=5.1, VServo=5.3, Flags=3)]
    topics, _, _ = parse(monkeypatch, tmp_bin_path, messages)
    power = topics["system_power"]
    assert power["voltage5v_v"].iloc[0] == pytest.approx(5.1)
    assert power["servo_rail_v"].iloc[0] == pytest.approx(5.3)
    assert power["power_flags"].iloc[0] == 3


def test_board_and_airframe_from_startup_messages(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("MSG", 1.0, Message="ArduCopter V4.5.7 (2a3dc4b7)"),
        FakeDFMessage("MSG", 1.0, Message="ChibiOS: 6a85082c"),
        FakeDFMessage("MSG", 1.0, Message="CubeOrange 0035002A 30395112 34313234"),
        FakeDFMessage("MSG", 1.0, Message="Frame: HEXA/X"),
    ]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages, params={"FRAME_CLASS": 1, "FRAME_TYPE": 1})
    assert metadata.hardware_id == "CubeOrange"
    # the parameters win over the banner
    assert metadata.airframe_name == "Quad X"


def test_frame_banner_used_without_frame_params(monkeypatch, tmp_bin_path):
    messages = [
        FakeDFMessage("MSG", 1.0, Message="ArduCopter V4.5.7 (2a3dc4b7)"),
        FakeDFMessage("MSG", 1.0, Message="Frame: HEXA/X"),
    ]
    _, _, metadata = parse(monkeypatch, tmp_bin_path, messages)
    assert metadata.airframe_name == "HEXA/X"


def test_progress_reported_through_the_index_and_the_read(monkeypatch, tmp_bin_path):
    from pymavlink import DFReader
    from flightmd_core.services import ardupilot_parser

    monkeypatch.setattr(ardupilot_parser, "PROGRESS_EVERY", 2)
    messages = [FakeDFMessage("IMU", 10.0 + k * 0.01, I=0, GyrX=0, GyrY=0, GyrZ=0, AccX=0, AccY=0, AccZ=-9.8)
                for k in range(10)]
    reader = FakeDFReader(messages, {})
    reader.percent = 50.0

    def open_reader(path, progress_callback=None):
        progress_callback(100)  # index pass done
        return reader
    monkeypatch.setattr(DFReader, "DFReader_binary", open_reader)

    seen = []
    ArduPilotBinParser().parse(tmp_bin_path, progress=seen.append)
    assert seen[0] == pytest.approx(0.2)
    assert seen[-1] == pytest.approx(0.6)
    assert all(0 <= f <= 1 for f in seen)
