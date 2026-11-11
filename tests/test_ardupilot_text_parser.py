"""
ArduPilotTextParser: the text form of a dataflash log goes through pymavlink's
DFReader_text and then ArduPilotBinParser's mapping. One test fakes the reader, the
other runs the real DFReader_text on a small hand-written log.
"""

import pytest

from flightmd_core.services.ardupilot_text_parser import ArduPilotTextParser


class FakeMessage:
    def __init__(self, mtype, t, **fields):
        self._mtype = mtype
        self._fields = {"TimeUS": int(round(t * 1e6)), **fields}

    def get_type(self):
        return self._mtype

    def to_dict(self):
        return dict(self._fields)


class FakeReader:
    def __init__(self, messages, params):
        self._messages = iter(messages)
        self.params = params

    def recv_match(self, type=None):
        for m in self._messages:
            if type is None or m.get_type() in type:
                return m
        return None


def test_uses_the_text_reader(monkeypatch, tmp_path):
    from pymavlink import DFReader

    opened = []
    reader = FakeReader([
        FakeMessage("IMU", 5.0, I=0, GyrX=0.1, GyrY=0.2, GyrZ=0.3, AccX=0.0, AccY=0.0, AccZ=-9.8),
        FakeMessage("IMU", 5.1, I=0, GyrX=0.2, GyrY=0.3, GyrZ=0.4, AccX=0.0, AccY=0.0, AccZ=-9.8),
    ], {"BATT_CAPACITY": 5200.0})

    def fake_text(path, *a, **k):
        opened.append(path)
        return reader

    def no_binary(*a, **k):
        raise AssertionError("a text log must not go through DFReader_binary")

    monkeypatch.setattr(DFReader, "DFReader_text", fake_text)
    monkeypatch.setattr(DFReader, "DFReader_binary", no_binary)
    p = tmp_path / "flight.log"
    p.write_text("FMT, 128, 89, FMT, BBnNZ, Type,Length,Name,Format,Columns\n")

    topics, params, _ = ArduPilotTextParser().parse(str(p))
    assert opened == [str(p)]
    assert list(topics["vehicle_angular_velocity"]["rollspeed"]) == pytest.approx([0.1, 0.2])
    assert list(topics["vehicle_angular_velocity"]["timestamp"]) == [0, 100_000]
    assert params["BATT_CAPACITY"] == 5200.0


TEXT_LOG = """\
FMT, 128, 89, FMT, BBnNZ, Type,Length,Name,Format,Columns
FMT, 64, 31, PARM, QNf, TimeUS,Name,Value
FMT, 91, 75, MSG, QZ, TimeUS,Message
FMT, 129, 45, IMU, QBffffff, TimeUS,I,GyrX,GyrY,GyrZ,AccX,AccY,AccZ
FMT, 130, 50, GPS, QBBIHBcLLeffffB, TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U
FMT, 147, 47, BAT, QBfffffcf, TimeUS,Inst,Volt,VoltR,Curr,CurrTot,EnrgTot,Temp,Res
PARM, 1000, BATT_CAPACITY, 5200
PARM, 1000, ATC_RAT_RLL_P, 0.135
MSG, 2000, ArduCopter V4.5.1 (12345678)
IMU, 1000000, 0, 0.0100, 0.0200, 0.0300, 0.1000, 0.2000, -9.8000
IMU, 1002500, 0, 0.0110, 0.0210, 0.0310, 0.1100, 0.2100, -9.8100
GPS, 1004000, 0, 3, 123456000, 2300, 12, 0.80, -35.3632621, 149.1652374, 584.10, 0.00, 0.00, 0.00, 0.00, 1
IMU, 1005000, 0, 0.0120, 0.0220, 0.0320, 0.1200, 0.2200, -9.8200
BAT, 1006000, 0, 16.20, 16.30, 12.50, 100.00, 2.00, 25.00, 0.010
GPS, 1204000, 0, 3, 123456200, 2300, 13, 0.70, -35.3632700, 149.1652400, 585.20, 0.00, 0.00, 0.00, 0.00, 1
IMU, 1207500, 0, 0.0130, 0.0230, 0.0330, 0.1300, 0.2300, -9.8300
"""


def test_real_text_log(tmp_path):
    p = tmp_path / "flight.log"
    p.write_bytes(TEXT_LOG.encode("ascii"))
    topics, params, meta = ArduPilotTextParser().parse(str(p))

    gyro = topics["vehicle_angular_velocity"]
    assert list(gyro["rollspeed"]) == pytest.approx([0.01, 0.011, 0.012, 0.013])
    accel = topics["sensor_accel"]
    assert list(accel["z"]) == pytest.approx([-9.8, -9.81, -9.82, -9.83])

    # text logs hold degrees and metres already; the topic wants degE7 and mm
    gps = topics["vehicle_gps_position"]
    assert list(gps["lat"]) == [-353632621, -353632700]
    assert list(gps["lon"]) == [1491652374, 1491652400]
    assert gps["alt"].iloc[0] == pytest.approx(584_100)
    assert list(gps["satellites_used"]) == [12, 13]

    bat = topics["battery_status"]
    assert bat["voltage_v"].iloc[0] == pytest.approx(16.2)
    assert bat["current_a"].iloc[0] == pytest.approx(12.5)

    assert params["BATT_CAPACITY"] == 5200
    assert params["ATC_RAT_RLL_P"] == pytest.approx(0.135)
    assert meta.firmware_version == "ArduCopter V4.5.1 (12345678)"
    assert meta.vehicle_type == "Copter"
