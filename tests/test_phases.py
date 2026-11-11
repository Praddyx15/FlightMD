"""
Tests for flight-phase windows and the vehicle profile.
"""

import math

import numpy as np
import pandas as pd

from flightmd_core.analysers.phases import flight_phases
from flightmd_core.analysers.vehicle import Vehicle, rate_gain_names, vehicle_from_params


def status(rows):
    return pd.DataFrame(rows, columns=["timestamp", "arming_state"])


class TestFlightPhases:

    def test_no_status_falls_back_to_whole_log(self):
        p = flight_phases({})
        assert not p.known
        assert p.mask(np.array([0, 1e9])).all()

    def test_status_without_arming_column_falls_back(self):
        p = flight_phases({"vehicle_status": pd.DataFrame({"timestamp": [0, 1], "nav_state": [2, 2]})})
        assert not p.known

    def test_never_armed_falls_back(self):
        p = flight_phases({"vehicle_status": status([(0, 1), (5_000_000, 1)])})
        assert not p.known

    def test_armed_window(self):
        p = flight_phases({"vehicle_status": status([(0, 1), (10, 2), (20, 1)])})
        assert p.known
        assert p.armed == [(10.0, 20.0)]
        assert list(p.mask(np.array([5, 10, 15, 20, 25]), "armed")) == [False, True, True, True, False]

    def test_log_starting_armed_and_ending_armed(self):
        p = flight_phases({"vehicle_status": status([(100, 2), (200, 2)])})
        assert p.armed == [(-math.inf, math.inf)]

    def test_two_flights(self):
        p = flight_phases({"vehicle_status": status([(0, 1), (10, 2), (20, 1), (30, 2), (40, 1)])})
        assert p.armed == [(10.0, 20.0), (30.0, 40.0)]

    def test_in_air_from_land_detector(self):
        land = pd.DataFrame({"timestamp": [0, 12, 18], "landed": [True, False, True]})
        p = flight_phases({
            "vehicle_status": status([(0, 1), (10, 2), (20, 1)]),
            "vehicle_land_detected": land,
        })
        assert p.in_air == [(12.0, 18.0)]
        assert p.armed == [(10.0, 20.0)]

    def test_land_detector_never_clears_uses_armed(self):
        land = pd.DataFrame({"timestamp": [0, 12], "landed": [True, True]})
        p = flight_phases({
            "vehicle_status": status([(0, 1), (10, 2), (20, 1)]),
            "vehicle_land_detected": land,
        })
        assert p.in_air == p.armed


class TestVehicleProfile:

    def test_px4_mav_type(self):
        assert vehicle_from_params({"MAV_TYPE": 1}) == Vehicle("px4", "fixed_wing")
        assert vehicle_from_params({"MAV_TYPE": 2}) == Vehicle("px4", "multirotor")
        assert vehicle_from_params({"MAV_TYPE": 22}) == Vehicle("px4", "vtol")
        assert vehicle_from_params({"MAV_TYPE": 10}) == Vehicle("px4", "rover")

    def test_px4_autostart_fallback(self):
        assert vehicle_from_params({"SYS_AUTOSTART": 2100}).frame == "fixed_wing"
        assert vehicle_from_params({"SYS_AUTOSTART": 4001}).frame == "multirotor"
        assert vehicle_from_params({"SYS_AUTOSTART": 13000}).frame == "vtol"

    def test_ardupilot(self):
        assert vehicle_from_params({"FRAME_CLASS": 1, "ATC_RAT_RLL_P": 0.1}) == Vehicle("ardupilot", "multirotor")
        assert vehicle_from_params({"RLL2SRV_P": 1.0, "ARMING_CHECK": 1}) == Vehicle("ardupilot", "fixed_wing")
        assert vehicle_from_params({"Q_ENABLE": 1, "RLL_RATE_P": 0.1}).frame == "vtol"
        assert vehicle_from_params({"ATC_STR_RAT_P": 0.2}).frame == "rover"

    def test_vtol_and_rover_get_no_rate_gain(self):
        assert rate_gain_names(Vehicle("px4", "vtol"), "roll") == (None, None)
        assert rate_gain_names(Vehicle("px4", "rover"), "roll") == (None, None)
        assert rate_gain_names(Vehicle("px4", "multirotor"), "roll") == ("MC_ROLLRATE_P", "MC_ROLLRATE_D")
