"""
The analysers a report runs: the built-ins plus any installed plugins.

A plugin is a BaseAnalyser subclass exposed under the `flightmd.analysers`
entry point group, e.g. in the plugin's pyproject.toml:

    [project.entry-points."flightmd.analysers"]
    prop_strike = "my_pkg.prop_strike:PropStrikeAnalyser"

It declares what it needs (required_topics / required_any / required_columns /
formats) and its score weight on the class; see docs/plugins.md. A plugin
that fails to import, isn't a BaseAnalyser, or reuses a built-in name is
left out with a warning, never allowed to stop an analysis.
"""

import logging
from importlib.metadata import entry_points

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.oscillation import OscillationAnalyser
from flightmd_core.analysers.vibration import VibrationAnalyser
from flightmd_core.analysers.ekf import EKFAnalyser
from flightmd_core.analysers.battery import BatteryAnalyser
from flightmd_core.analysers.gps import GPSAnalyser
from flightmd_core.analysers.parameters import ParameterAnalyser
from flightmd_core.analysers.motors import MotorAnalyser
from flightmd_core.analysers.ascent_profile import AscentProfileAnalyser
from flightmd_core.analysers.power import PowerAnalyser

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "flightmd.analysers"

BUILTINS: list[type[BaseAnalyser]] = [
    OscillationAnalyser,
    VibrationAnalyser,
    EKFAnalyser,
    BatteryAnalyser,
    GPSAnalyser,
    ParameterAnalyser,
    MotorAnalyser,
    AscentProfileAnalyser,
    PowerAnalyser,
]


def plugin_classes() -> list[type[BaseAnalyser]]:
    taken = {c.name for c in BUILTINS}
    out = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception as e:
            # thrid-party code; a broken plugin must not take the report down
            logger.warning(f"analyser plugin {ep.name!r} failed to load: {e}")
            continue
        if not (isinstance(cls, type) and issubclass(cls, BaseAnalyser)):
            logger.warning(f"analyser plugin {ep.name!r} is not a BaseAnalyser subclass, ignored")
            continue
        if getattr(cls, "name", None) in taken:
            logger.warning(f"analyser plugin {ep.name!r} reuses the name {cls.name!r}, ignored")
            continue
        taken.add(cls.name)
        out.append(cls)
    return out


def analyser_classes() -> list[type[BaseAnalyser]]:
    return BUILTINS + plugin_classes()


def load_analysers(metadata=None) -> list[BaseAnalyser]:
    """Fresh instances of every analyser. Pass the log's FlightMetadata so
    modules that care about firmware version or log format can see it."""
    out = []
    for cls in analyser_classes():
        try:
            a = cls()
        except Exception as e:
            logger.warning(f"analyser {getattr(cls, 'name', cls.__name__)!r} failed to start: {e}")
            continue
        a.metadata = metadata
        out.append(a)
    return out


def module_weights() -> dict[str, float]:
    """name -> score weight; modules with weight 0 are left out."""
    return {c.name: float(c.weight) for c in analyser_classes() if c.weight and c.weight > 0}
