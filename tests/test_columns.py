"""
ColumnBuffer, and the dataflash row getters that feed it, checked against pymavlink's own
DFMessage decoding.
"""

import math

import numpy as np
import pytest

from flightmd_core.services.ardupilot_parser import _row_getter, _type_count
from flightmd_core.services.columns import MIN_ROWS, ColumnBuffer


class TestColumnBuffer:
    def test_rows_become_float_columns(self):
        buf = ColumnBuffer(["timestamp", "a", "b"], size=4)
        buf.append((1, 2.5, None))
        buf.append([2, np.int64(3), 4.0])
        df = buf.frame()

        assert list(df.columns) == ["timestamp", "a", "b"]
        assert len(buf) == 2
        assert df["timestamp"].tolist() == [1.0, 2.0]
        assert df["a"].tolist() == [2.5, 3.0]
        assert math.isnan(df["b"].iloc[0])
        assert df["b"].iloc[1] == 4.0
        assert all(dt == np.float64 for dt in df.dtypes)

    def test_grows_past_the_size_hint(self):
        buf = ColumnBuffer(["t", "v"], size=0)
        n = MIN_ROWS * 5 + 3
        for i in range(n):
            buf.append((i, i * 2))
        df = buf.frame()
        assert len(df) == n
        assert df["v"].iloc[-1] == (n - 1) * 2
        assert df["t"].is_monotonic_increasing

    def test_exact_size_hint_is_not_exceeded(self):
        buf = ColumnBuffer(["t"], size=MIN_ROWS * 2)
        block = buf._data
        for i in range(MIN_ROWS * 2):
            buf.append((i,))
        assert buf._data is block

    def test_frame_is_a_copy(self):
        buf = ColumnBuffer(["t"])
        buf.append((1,))
        df = buf.frame()
        buf.append((2,))
        buf._data[0, 0] = 99
        assert df["t"].tolist() == [1.0]

    def test_empty_buffer_gives_empty_frame(self):
        df = ColumnBuffer(["t", "x"]).frame()
        assert df.empty
        assert list(df.columns) == ["t", "x"]

    def test_duplicate_columns_rejected(self):
        with pytest.raises(ValueError):
            ColumnBuffer(["t", "x", "x"])

    def test_text_value_is_an_error_not_a_silent_nan(self):
        buf = ColumnBuffer(["t"])
        with pytest.raises(ValueError):
            buf.append(("abc",))


def _gps_message(apply_multiplier=True):
    from pymavlink import DFReader

    fmt = DFReader.DFFormat(
        130, "GPS", 0, "QBBIHBcLLeffffB",
        "TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U",
    )
    elements = [12_345_678, 1, 3, 345_600_000, 2300, 14, 90, 377_749_000, -1_224_194_000,
                10_050, 1.5, 90.0, -0.2, 0.0, 1]
    if not apply_multiplier:
        # text logs: every element is the printed string, already in real units
        elements = ["12345678", "1", "3", "345600000", "2300", "14", "0.9", "37.7749",
                    "-122.4194", "100.5", "1.5", "90", "-0.2", "0", "1"]
    return DFReader.DFMessage(fmt, elements, apply_multiplier, None)


GPS_FIELDS = ["Lat", ("Lng", "Lon"), "Alt", "NSats", "HDop", "Status", "GWk", "GMS"]


class TestRowGetter:
    @pytest.mark.parametrize("apply_multiplier", [True, False])
    def test_matches_dfmessage_decoding(self, apply_multiplier):
        msg = _gps_message(apply_multiplier)
        row = list(_row_getter(msg, "I", GPS_FIELDS)(msg))
        d = msg.to_dict()

        assert row[0] == d["TimeUS"]
        assert row[1] == d["I"]
        expected = [d["Lat"], d["Lng"], d["Alt"], d["NSats"], d["HDop"], d["Status"], d["GWk"], d["GMS"]]
        assert row[2:] == pytest.approx(expected)

    def test_plain_float_messages_take_the_fast_path(self):
        from pymavlink import DFReader

        fmt = DFReader.DFFormat(131, "IMU", 0, "QBffffff", "TimeUS,I,GyrX,GyrY,GyrZ,AccX,AccY,AccZ")
        msg = DFReader.DFMessage(fmt, [1000, 2, 0.1, 0.2, 0.3, 1.0, 2.0, -9.8], True, None)
        fields = ["GyrX", "GyrY", "GyrZ", "AccX", "AccY", "AccZ"]
        row = _row_getter(msg, "I", fields)(msg)
        assert tuple(row) == (1000, 2, 0.1, 0.2, 0.3, 1.0, 2.0, -9.8)

    def test_missing_fields_and_instance_fall_back(self):
        from pymavlink import DFReader

        # pre-4.0 IMU2: no instance field, no AccZ in this made-up format
        fmt = DFReader.DFFormat(132, "IMU2", 0, "Qfffff", "TimeUS,GyrX,GyrY,GyrZ,AccX,AccY")
        msg = DFReader.DFMessage(fmt, [5000, 0.1, 0.2, 0.3, 1.0, 2.0], True, None)
        row = _row_getter(msg, "I", ["GyrX", "GyrY", "GyrZ", "AccX", "AccY", "AccZ"])(msg)
        assert row[0] == 5000
        assert row[1] == 1  # IMU2 is the second IMU
        assert math.isnan(row[-1])

    def test_time_ms_becomes_us(self):
        from pymavlink import DFReader

        fmt = DFReader.DFFormat(133, "VIBE", 0, "Ifff", "TimeMS,VibeX,VibeY,VibeZ")
        msg = DFReader.DFMessage(fmt, [1500, 1.0, 2.0, 3.0], True, None)
        row = _row_getter(msg, "IMU", ["VibeX", "VibeY", "VibeZ"])(msg)
        assert row[0] == 1_500_000
        assert row[1] == 0


class TestTypeCount:
    def test_binary_reader_counts_by_type_id(self):
        class Reader:
            name_to_id = {"IMU": 5, "IMU2": 6}
            counts = [0] * 256

        r = Reader()
        r.counts[5], r.counts[6] = 1000, 400
        assert _type_count(r, ("IMU", "IMU2", "IMU3")) == 1400

    def test_text_reader_counts_by_name(self):
        class Reader:
            name_to_id = {}
            counts = {"GPS": 30}

        assert _type_count(Reader(), ("GPS", "GPS2")) == 30

    def test_reader_without_index(self):
        assert _type_count(object(), ("GPS",)) == 0
