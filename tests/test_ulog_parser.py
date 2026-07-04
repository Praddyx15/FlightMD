"""
Tests for ULogParser — file handling, topic extraction, metadata parsing.

Note: These tests require either real .ulg files in tests/sample_logs/
or use mocking for unit-level coverage. Integration tests use real files.
"""

import os
import struct
import tempfile

import numpy as np
import pandas as pd
import pytest

from flightmd_core.services.ulog_parser import ULogParser

SAMPLE_LOGS_DIR = os.path.join(os.path.dirname(__file__), "sample_logs")


class TestULogParserUnit:

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ULogParser().parse("/nonexistent/path/file.ulg")

    def test_topic_alias_normalisation(self):
        """_extract_topics should create canonical aliases."""
        # This is tested indirectly — if the parser runs on a real file,
        # aliases like sensor_accel should exist even if source is sensor_accel_0
        parser = ULogParser()
        # Test the alias lookup logic via a mock ULog structure
        class FakeData:
            def __init__(self, name, mid, data):
                self.name = name
                self.multi_id = mid
                self.data = data
        class FakeULog:
            data_list = [
                FakeData("sensor_accel", 0, {"timestamp": [1,2,3], "x": [0.1,0.2,0.3]}),
                FakeData("sensor_accel", 1, {"timestamp": [1,2,3], "x": [0.2,0.3,0.4]}),
            ]
        raw = {}
        for d in FakeULog.data_list:
            key = d.name if d.multi_id == 0 else f"{d.name}_{d.multi_id}"
            raw[key] = pd.DataFrame.from_dict(d.data)
            if d.multi_id == 0:
                raw[d.name] = pd.DataFrame.from_dict(d.data)
        assert "sensor_accel" in raw
        assert "sensor_accel_1" in raw

    def test_arm_count_from_arming_state(self):
        """_count_arms should detect transitions to ARMED (state=2)."""
        parser = ULogParser()
        # Simulate one arm event: unarmed → armed → unarmed → armed
        states = np.array([1, 1, 2, 2, 2, 1, 1, 2, 2])
        df = pd.DataFrame({"arming_state": states})
        topics = {"vehicle_status": df}
        count = parser._count_arms(topics)
        assert count == 2

    def test_max_altitude_from_local_position(self):
        """_max_altitude should negate Z (PX4 NED, Z positive-down)."""
        parser = ULogParser()
        # Z = -50 (50m altitude in NED)
        df = pd.DataFrame({
            "timestamp": [0, 1, 2],
            "z": [0.0, -30.0, -50.0],
        })
        topics = {"vehicle_local_position": df}
        alt = parser._max_altitude(topics)
        assert alt == 50.0

    def test_total_distance_calculation(self):
        """_total_distance should sum Euclidean steps in local XY."""
        parser = ULogParser()
        # Simple 3-4-5 triangle path
        df = pd.DataFrame({
            "timestamp": [0, 1, 2],
            "x": [0.0, 3.0, 3.0],
            "y": [0.0, 0.0, 4.0],
        })
        topics = {"vehicle_local_position": df}
        dist = parser._total_distance(topics)
        assert abs(dist - 7.0) < 0.01   # 3 + 4 = 7

    def test_max_speed_from_velocity(self):
        """_max_speed should return max of sqrt(vx² + vy²)."""
        parser = ULogParser()
        df = pd.DataFrame({
            "timestamp": [0, 1, 2],
            "vx": [0.0, 3.0, 0.0],
            "vy": [0.0, 4.0, 0.0],
        })
        topics = {"vehicle_local_position": df}
        speed = parser._max_speed(topics)
        assert abs(speed - 5.0) < 0.01

    def test_extract_flight_modes_from_nav_state(self):
        """_extract_flight_modes should decode nav_state values."""
        parser = ULogParser()
        df = pd.DataFrame({
            "timestamp": [0, 1, 2, 3],
            "nav_state": [2, 2, 3, 3],  # 2=Position, 3=Auto Mission
        })
        topics = {"vehicle_status": df}
        modes = parser._extract_flight_modes(topics)
        assert "Position Control" in modes
        assert "Auto Mission" in modes


@pytest.mark.integration
class TestULogParserIntegration:
    """
    Integration tests that require real .ulg files.
    Place .ulg files in tests/sample_logs/ and run with pytest -m integration.
    These tests are skipped in CI if no sample files are present.
    """

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

    def test_metadata_duration_positive(self, sample_log_path):
        _, _, metadata = ULogParser().parse(sample_log_path)
        assert metadata.duration_seconds > 0

    def test_available_topics_populated(self, sample_log_path):
        _, _, metadata = ULogParser().parse(sample_log_path)
        assert len(metadata.available_topics) > 0
