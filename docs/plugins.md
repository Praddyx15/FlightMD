# Analyser plugins

A plugin is a `BaseAnalyser` subclass in its own package, registered under the
`flightmd.analysers` entry point group. Once the package is installed next to
`flightmd-core`, every report runs it alongside the built-in modules.

```python
# my_pkg/prop_strike.py
from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import AnalyserResult, Category, Finding, Severity


class PropStrikeAnalyser(BaseAnalyser):
    name = "prop_strike"                 # unique, snake_case; also the key in trends
    display_name = "Prop Strike"
    required_topics = ["esc_status"]     # all must be present
    required_columns = {"esc_status": ["esc[0].esc_rpm"]}
    weight = 5.0                         # share of the overall score; 0 = not scored

    def analyse(self, topics, params):
        phases = flight_phases(topics)
        ...
        return AnalyserResult(analyser=self.name, display_name=self.display_name,
                              findings=findings, health_score=score)
```

```toml
# the plugin's pyproject.toml
[project.entry-points."flightmd.analysers"]
prop_strike = "my_pkg.prop_strike:PropStrikeAnalyser"
```

## What the class declares

| attribute | meaning |
|---|---|
| `required_topics` | every one must be in the log, or the module is skipped |
| `required_any` | at least one must be in the log |
| `required_columns` | `{topic: [columns]}` a present topic must carry |
| `formats` | detector ids it understands (`px4_ulog`, `ardupilot_bin`, `mavlink_tlog`, ...); empty = all |
| `weight` | score weight. The built-ins sum to 100; a plugin's weight is added to the total, so 5 means "about as much as the parameter check" |

When a declared input is missing the module is skipped with a reason naming
it, and the report lists it as not assessed. `self.metadata` is the log's
`FlightMetadata` (firmware version, vehicle type, source format) when the
pipeline passes it in; it can be `None`.

## Rules

- Topic names and units follow the topic contract in `services/ulog_parser.py`:
  log-relative `timestamp` in µs, PX4 names for every format.
- Return `self._skip(reason)` when there's nothing to check, never a clean 100.
- Set `Finding.kind` (`"<module>.<check>"`) and `Finding.params` for any
  parameter your recommendation names.
- An exception in `analyse()` becomes a skipped result; it won't take the
  report down. A plugin that fails to import, isn't a `BaseAnalyser`, or reuses
  a built-in name is left out with a warning in the log.
- Plugins run with the server's permissions. Only install ones you trust.
