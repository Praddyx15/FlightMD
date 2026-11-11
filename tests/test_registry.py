"""
Tests for the analyser registry: built-ins, entry-point plugins, declared
inputs and plugin score weights.
"""

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from flightmd_core.analysers import registry
from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import AnalyserResult
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.score_calculator import ScoreCalculator


class PropStrikeAnalyser(BaseAnalyser):
    name = "prop_strike"
    display_name = "Prop Strike"
    required_topics = ["esc_status"]
    required_columns = {"esc_status": ["esc[0].esc_rpm"]}
    weight = 10.0

    def analyse(self, topics, params):
        return AnalyserResult(analyser=self.name, display_name=self.display_name,
                              findings=[], health_score=50.0)


class Clash(PropStrikeAnalyser):
    name = "vibration"


class FakeEntryPoint:
    def __init__(self, name, obj=None, error=None):
        self.name = name
        self._obj = obj
        self._error = error

    def load(self):
        if self._error:
            raise self._error
        return self._obj


@pytest.fixture
def plugins(monkeypatch):
    eps: list[FakeEntryPoint] = []

    def fake_entry_points(group):
        assert group == "flightmd.analysers"
        return list(eps)

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)
    return eps


def test_builtins_without_plugins(plugins):
    names = [a.name for a in registry.load_analysers()]
    assert names == [c.name for c in registry.BUILTINS]
    assert len(set(names)) == len(names)


def test_builtin_weights_sum_to_100(plugins):
    assert sum(registry.module_weights().values()) == 100.0


def test_plugin_is_loaded_with_metadata(plugins):
    plugins.append(FakeEntryPoint("prop_strike", PropStrikeAnalyser))
    meta = FlightMetadata(duration_seconds=10.0, firmware_version="v1.14.0")
    analysers = registry.load_analysers(meta)
    plugin = [a for a in analysers if a.name == "prop_strike"]
    assert len(plugin) == 1
    assert plugin[0].metadata is meta
    assert all(a.metadata is meta for a in analysers)


def test_plugin_weight_counts_in_the_score(plugins):
    plugins.append(FakeEntryPoint("prop_strike", PropStrikeAnalyser))
    assert registry.module_weights()["prop_strike"] == 10.0
    results = [
        AnalyserResult(analyser="oscillation", display_name="o", findings=[], health_score=100.0),
        AnalyserResult(analyser="prop_strike", display_name="p", findings=[], health_score=50.0),
    ]
    score, _, _ = ScoreCalculator().calculate(results)
    assert score == round((100.0 * 20 + 50.0 * 10) / 30, 1)
    assert ScoreCalculator().assessed_fraction(results) == round(30 / 110, 3)


@pytest.mark.parametrize("ep", [
    FakeEntryPoint("broken", error=ImportError("no module named prop_strike")),
    FakeEntryPoint("not_a_class", obj=lambda: None),
    FakeEntryPoint("clash", obj=Clash),
])
def test_bad_plugins_are_left_out(plugins, caplog, ep):
    plugins.append(ep)
    with caplog.at_level(logging.WARNING):
        names = [a.name for a in registry.load_analysers()]
    assert names == [c.name for c in registry.BUILTINS]
    assert ep.name in caplog.text


def test_missing_topic_skips_with_reason():
    result = PropStrikeAnalyser().safe_analyse({}, {})
    assert result.skipped
    assert "esc_status" in result.skip_reason
    assert not PropStrikeAnalyser().is_applicable(set())


def test_missing_column_skips_with_reason():
    df = pd.DataFrame({"timestamp": np.arange(10), "esc_count": 4})
    result = PropStrikeAnalyser().safe_analyse({"esc_status": df}, {})
    assert result.skipped
    assert "esc[0].esc_rpm" in result.skip_reason


def test_inputs_present_runs():
    df = pd.DataFrame({"timestamp": np.arange(10), "esc[0].esc_rpm": 5000.0})
    result = PropStrikeAnalyser().safe_analyse({"esc_status": df}, {})
    assert not result.skipped
    assert result.health_score == 50.0


def test_format_restriction():
    class TlogOnly(PropStrikeAnalyser):
        formats = ["mavlink_tlog"]

    a = TlogOnly()
    a.metadata = SimpleNamespace(source_format="px4_ulog")
    df = pd.DataFrame({"timestamp": np.arange(10), "esc[0].esc_rpm": 5000.0})
    result = a.safe_analyse({"esc_status": df}, {})
    assert result.skipped
    assert "px4_ulog" in result.skip_reason


def test_skip_result_names_what_is_missing():
    assert "esc_status" in PropStrikeAnalyser().skip_result({"sensor_accel"}).skip_reason


def test_one_of_topics():
    from flightmd_core.analysers.vibration import VibrationAnalyser
    a = VibrationAnalyser()
    assert a.is_applicable({"vibration"})
    assert a.is_applicable({"vehicle_imu_status"})
    assert not a.is_applicable({"battery_status"})
