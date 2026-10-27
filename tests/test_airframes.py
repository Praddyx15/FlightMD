import pytest

from flightmd_core.services.airframes import ardupilot_frame, px4_airframe


@pytest.mark.parametrize("autostart, name", [
    (4001, "Generic Quadcopter"),
    (4001.0, "Generic Quadcopter"),
    ("13000", "Generic Standard VTOL"),
    (2100, "Generic Standard Plane"),
    (50000, "Generic Rover Differential"),
])
def test_px4_known_ids(autostart, name):
    assert px4_airframe(autostart)[0] == name


def test_px4_frame_type_comes_along():
    assert px4_airframe(4001) == ("Generic Quadcopter", "Quadrotor x")


@pytest.mark.parametrize("autostart", [None, 0, 999999, "abc"])
def test_px4_unknown_ids(autostart):
    assert px4_airframe(autostart) == (None, None)


@pytest.mark.parametrize("params, vehicle, name", [
    ({"FRAME_CLASS": 1, "FRAME_TYPE": 1}, "Copter", "Quad X"),
    ({"FRAME_CLASS": 2, "FRAME_TYPE": 0}, "Copter", "Hexa Plus"),
    ({"FRAME_CLASS": 6, "FRAME_TYPE": 1}, "Copter", "Heli"),
    ({"FRAME_CLASS": 1, "FRAME_TYPE": 99}, "Copter", "Quad"),
    ({"FRAME_CLASS": 1, "FRAME_TYPE": 1}, None, "Quad X"),
    ({"Q_ENABLE": 1, "Q_FRAME_CLASS": 1, "Q_FRAME_TYPE": 1}, "Plane", "QuadPlane Quad X"),
    ({"Q_ENABLE": 0}, "Plane", "Plane"),
    ({"Q_ENABLE": 1, "Q_FRAME_CLASS": 10}, "VTOL", "QuadPlane Single/Dual"),
    ({"FRAME_CLASS": 2, "FRAME_TYPE": 0}, "Rover", "Boat"),
    ({"FRAME_CLASS": 1, "FRAME_TYPE": 2}, "Rover", "Rover OmniX"),
    ({"FRAME_CLASS": 1, "CRUISE_SPEED": 2.0}, None, "Rover"),
    ({"FRAME_CONFIG": 1}, "Sub", "Vectored"),
])
def test_ardupilot_frames(params, vehicle, name):
    assert ardupilot_frame(params, vehicle) == name


def test_ardupilot_no_frame_params():
    assert ardupilot_frame({}, "Copter") is None
    assert ardupilot_frame({"FRAME_CLASS": 0}, "Copter") is None
