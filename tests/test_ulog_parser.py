import os

import numpy as np
import pandas as pd
import pytest

from flightmd_core.services.ulog_parser import ULogParser

SAMPLE_LOGS_DIR = os.path.join(os.path.dirname(__file__), "sample_logs")
START = 50_000_000  # ULog start_timestamp, boot µs


class FakeData:
    def __init__(self, name, multi_id, data):
        self.name = name
        self.multi_id = multi_id
        self.data = {k: np.asarray(v) for k, v in data.items()}


class FakeULog:
    def __init__(self, data_list, start=START):
        self.data_list = data_list
        self.start_timestamp = start
        self.last_timestamp = start + 10_000_000


def topics_of(*data):
    return ULogParser()._extract_topics(FakeULog(list(data)))


class TestExtractTopics:

    def test_instances_named_without_duplicates(self):
        topics = topics_of(
            FakeData("sensor_accel", 0, {"timestamp": [START + 1, START + 2], "x": [0.1, 0.2]}),
            FakeData("sensor_accel", 1, {"timestamp": [START + 1, START + 2], "x": [0.3, 0.4]}),
        )
        assert sorted(k for k in topics if k.startswith("sensor_accel")) == ["sensor_accel", "sensor_accel_1"]
        assert list(topics["sensor_accel_1"]["x"]) == pytest.approx([0.3, 0.4])

    def test_timestamps_are_log_relative(self):
        topics = topics_of(FakeData("vehicle_status", 0, {
            "timestamp": np.array([START, START + 500_000], dtype=np.uint64),
            "timestamp_sample": np.array([START - 100, START + 499_900], dtype=np.uint64),
            "arming_state": [1, 2],
        }))
        df = topics["vehicle_status"]
        assert list(df["timestamp"]) == [0, 500_000]
        assert list(df["timestamp_sample"]) == [-100, 499_900]

    def test_sensor_gps_aliased_and_new_field_names_normalised(self):
        # PX4 1.15 logs sensor_gps with float latitude_deg / longitude_deg / altitude_msl_m
        topics = topics_of(FakeData("sensor_gps", 0, {
            "timestamp": [START],
            "latitude_deg": [37.7749],
            "longitude_deg": [-122.4194],
            "altitude_msl_m": [12.5],
            "fix_type": [3],
        }))
        gps = topics["vehicle_gps_position"]
        assert gps["lat"].iloc[0] == 377749000
        assert gps["lon"].iloc[0] == -1224194000
        assert gps["alt"].iloc[0] == 12500

    def test_esc_status_trimmed_to_esc_count(self):
        data = {"timestamp": [START, START + 1], "esc_count": [4, 4]}
        for i in range(8):
            data[f"esc[{i}].esc_rpm"] = [5000, 5100] if i < 4 else [0, 0]
            data[f"esc[{i}].esc_current"] = [3.0, 3.1] if i < 4 else [0.0, 0.0]
        esc = topics_of(FakeData("esc_status", 0, data))["esc_status"]

        rpm_cols = [c for c in esc.columns if c.endswith("esc_rpm")]
        assert rpm_cols == [f"esc[{i}].esc_rpm" for i in range(4)]
        assert (esc["esc_count"] == 4).all()

    def test_esc_count_inferred_when_missing(self):
        data = {"timestamp": [START, START + 1]}
        for i in range(8):
            data[f"esc[{i}].esc_rpm"] = [5000, 5100] if i < 6 else [0, 0]
        esc = topics_of(FakeData("esc_status", 0, data))["esc_status"]
        assert (esc["esc_count"] == 6).all()
        assert "esc[6].esc_rpm" not in esc.columns

    def test_primary_ekf_instance_goes_under_bare_name(self):
        topics = topics_of(
            FakeData("estimator_selector_status", 0, {"timestamp": [START, START + 1, START + 2],
                                                      "primary_instance": [1, 1, 0]}),
            FakeData("estimator_status", 0, {"timestamp": [START], "pos_test_ratio": [0.0]}),
            FakeData("estimator_status", 1, {"timestamp": [START], "pos_test_ratio": [1.0]}),
        )
        assert topics["estimator_status"]["pos_test_ratio"].iloc[0] == 1.0
        assert topics["estimator_status_1"]["pos_test_ratio"].iloc[0] == 0.0


class TestULogParserUnit:

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ULogParser().parse("/nonexistent/path/file.ulg")

    def test_arm_count_from_arming_state(self):
        states = np.array([1, 1, 2, 2, 2, 1, 1, 2, 2])  # 2 = ARMED
        topics = {"vehicle_status": pd.DataFrame({"arming_state": states})}
        assert ULogParser()._count_arms(topics) == 2

    def test_max_altitude_from_local_position(self):
        # NED: z = -50 is 50 m up
        df = pd.DataFrame({"timestamp": [0, 1, 2], "z": [0.0, -30.0, -50.0]})
        assert ULogParser()._max_altitude({"vehicle_local_position": df}) == 50.0

    def test_total_distance_calculation(self):
        df = pd.DataFrame({
            "timestamp": [0, 1, 2],
            "x": [0.0, 3.0, 3.0],
            "y": [0.0, 0.0, 4.0],
        })
        assert ULogParser()._total_distance({"vehicle_local_position": df}) == pytest.approx(7.0)

    def test_max_speed_from_velocity(self):
        df = pd.DataFrame({
            "timestamp": [0, 1, 2],
            "vx": [0.0, 3.0, np.nan],
            "vy": [0.0, 4.0, np.nan],
        })
        assert ULogParser()._max_speed({"vehicle_local_position": df}) == pytest.approx(5.0)

    def test_extract_metadata_handles_integer_version_fields(self):
        # real firmware writes these info fields as ints
        class StubULog:
            start_timestamp = 0
            last_timestamp = 5_000_000
            msg_info_dict = {
                "ver_sw": 17695743,
                "ver_hw": 42,
                "ver_sw_release": 0x010E00FF,
                "sys_name": 7,
                "time_ref_utc": 19800,
            }
            initial_parameters = {"SYS_AUTOSTART": 4001}

        metadata = ULogParser()._extract_metadata(StubULog(), {})
        assert metadata.firmware_version == "17695743"
        assert metadata.hardware_id == "42"
        assert metadata.px4_version == "v1.14.0"
        assert metadata.vehicle_type == "7"
        assert metadata.airframe_id == 4001
        # time_ref_utc is a timezone offset, not a start time
        assert metadata.log_start_utc is None

    def test_log_start_utc_from_gps_time(self):
        gps = pd.DataFrame({
            "timestamp": [1_000_000, 2_000_000],
            "time_utc_usec": [0, 1_700_000_000_000_000],
        })

        class StubULog:
            start_timestamp = 0
            last_timestamp = 5_000_000
            msg_info_dict = {}
            initial_parameters = {}

        metadata = ULogParser()._extract_metadata(StubULog(), {"vehicle_gps_position": gps})
        # GPS time at t=2 s, so the log began 2 s earlier
        assert metadata.log_start_utc == "2023-11-14T22:13:18Z"

    @pytest.mark.parametrize("nav_state, name", [
        (2, "Position Control"),
        (3, "Auto Mission"),
        (10, "Acro"),
        (14, "Offboard"),
        (17, "Auto Takeoff"),
        (18, "Auto Land"),
        (21, "Orbit"),
    ])
    def test_nav_state_names(self, nav_state, name):
        df = pd.DataFrame({"timestamp": [0], "nav_state": [nav_state]})
        assert ULogParser()._extract_flight_modes({"vehicle_status": df}) == [name]

    def test_warnings_from_dropouts_and_corruption(self):
        class Drop:
            def __init__(self, ms):
                self.duration = ms

        class StubULog:
            file_corruption = True
            dropouts = [Drop(300), Drop(200)]

        warnings = ULogParser()._warnings(StubULog())
        assert len(warnings) == 2
        assert "2 times (0.5 s" in warnings[1]


@pytest.mark.integration
class TestULogParserIntegration:
    """Needs real .ulg files in tests/sample_logs/; skipped when there are none."""

    @pytest.fixture
    def sample_log_path(self):
        logs = [
            f for f in os.listdir(SAMPLE_LOGS_DIR)
            if f.endswith(".ulg")
        ] if os.path.exists(SAMPLE_LOGS_DIR) else []
        if not logs:
            pytest.skip("No .ulg sample files found in tests/sample_logs/")
        return os.path.join(SAMPLE_LOGS_DIR, logs[0])

    def test_parse_returns_three_outputs(self, sample_log_path):
        topics, params, metadata = ULogParser().parse(sample_log_path)
        assert isinstance(topics, dict)
        assert isinstance(params, dict)
        assert metadata.duration_seconds > 0

    def test_topics_are_dataframes(self, sample_log_path):
        topics, _, _ = ULogParser().parse(sample_log_path)
        for name, df in topics.items():
            assert isinstance(df, pd.DataFrame), f"{name} is not a DataFrame"
            assert len(df) > 0, f"{name} is empty"

    def test_params_are_floats(self, sample_log_path):
        _, params, _ = ULogParser().parse(sample_log_path)
        for k, v in params.items():
            assert isinstance(v, float), f"{k} value {v!r} is not float"

    def test_available_topics_populated(self, sample_log_path):
        _, _, metadata = ULogParser().parse(sample_log_path)
        assert len(metadata.available_topics) > 0


class TestMetadataDecoding:

    class StubULog:
        start_timestamp = 0
        last_timestamp = 5_000_000
        msg_info_dict = {"ver_hw": "CUBEPILOT_CUBEORANGE", "ver_hw_subtype": "V2", "sys_name": "PX4"}
        initial_parameters = {"SYS_AUTOSTART": 13000}

    def test_airframe_name_and_board(self):
        metadata = ULogParser()._extract_metadata(self.StubULog(), {})
        assert metadata.airframe_id == 13000
        assert metadata.airframe_name == "Generic Standard VTOL"
        assert metadata.hardware_id == "CUBEPILOT_CUBEORANGE (V2)"

    def test_unknown_airframe_id_has_no_name(self):
        stub = self.StubULog()
        stub.initial_parameters = {"SYS_AUTOSTART": 987654}
        assert ULogParser()._extract_metadata(stub, {}).airframe_name is None

    @pytest.mark.parametrize("status, expected", [
        ({"vehicle_type": [0, 1, 1], "is_vtol": [False, False, False]}, "Copter"),
        ({"vehicle_type": [2, 2], "is_vtol": [False, False]}, "Plane"),
        ({"vehicle_type": [1, 2], "is_vtol": [True, True]}, "VTOL"),
        ({"vehicle_type": [3]}, "Rover"),
        ({"is_rotary_wing": [True, True]}, "Copter"),
    ])
    def test_vehicle_type_from_vehicle_status(self, status, expected):
        n = len(next(iter(status.values())))
        df = pd.DataFrame({"timestamp": list(range(n)), **status})
        metadata = ULogParser()._extract_metadata(self.StubULog(), {"vehicle_status": df})
        assert metadata.vehicle_type == expected

    def test_vehicle_type_falls_back_to_sys_name(self):
        metadata = ULogParser()._extract_metadata(self.StubULog(), {})
        assert metadata.vehicle_type == "PX4"


def test_required_topics_include_imu_status_and_power():
    from flightmd_core.services.ulog_parser import REQUIRED_ULOG_TOPICS

    assert "vehicle_imu_status" in REQUIRED_ULOG_TOPICS
    assert "system_power" in REQUIRED_ULOG_TOPICS


def test_progress_wrapper_reports_file_position(tmp_path, monkeypatch):
    from flightmd_core.services import ulog_parser

    monkeypatch.setattr(ulog_parser, "PROGRESS_EVERY", 2)
    p = tmp_path / "x.bin"
    p.write_bytes(b"x" * 100)
    seen = []
    with open(p, "rb") as f:
        w = ulog_parser._Progress(f, 100, seen.append)
        assert w.read(10) == b"x" * 10
        w.read(30)
        w.read(10)
        w.read(10)
        assert w.tell() == 60
        w.seek(0)
        assert w.read(5) == b"xxxxx"
    assert seen == [pytest.approx(0.1), pytest.approx(0.5)]
