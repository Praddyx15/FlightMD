# Analyser framework and checks low-level design

FMD-LLD-ANL, issue 1, 2026-11-22.

As built. Requirements: `05-requirements/hlr-anl.sdoc`, `05-requirements/llr-anl.sdoc`. The thresholds
below are copied from the code for orientation; the LLR are the requirement (RS-18) and a change to a
number is a requirement change.

## 1 Purpose and code

The framework runs every check on the parsed topics and turns each into one `AnalyserResult`: findings,
a 0-100 module score, key metrics, or a skip with its reason. This item holds the framework and the five
checks that are not flight dynamics.

| File | Contents | LLR |
|---|---|---|
| `analysers/base.py` | `BaseAnalyser`: declared inputs, `is_applicable`, `missing_inputs`, `safe_analyse`, `_skip` | 001..006 |
| `analysers/registry.py`, `analysers/__init__.py` | Built-in list and order, plugin entry points, weights | 007..011 |
| `analysers/helpers.py` | Column lookup, runs, rates, downsampling, time windows, confidence | 012..017 |
| `analysers/phases.py` | Armed and in-air windows (`FlightPhases`) | 018..024 |
| `analysers/vehicle.py` | Autopilot and frame type from the parameters; rate gain names | 025..028 |
| `analysers/gps.py` | GPS check | 029..042 |
| `analysers/battery.py` | Battery check | 043..054 |
| `analysers/motors.py` | Motor and ESC check | 055..064 |
| `analysers/power.py` | Board power check (weight 0) | 065..069 |
| `analysers/parameters.py` | Parameter range and combination check; firmware tables | 070..087 |
| `scripts/gen_param_tables.py` | Generator of the firmware parameter tables (data) | 088..094 |

## 2 Structure and data flow

```
load_analysers(metadata) -> [built-ins in fixed order] + [plugins from entry points]
for each: missing_inputs(topics) is None ? safe_analyse(topics, params) : skipped result
safe_analyse: analyse() inside try; an exception becomes a skipped result with the error text
analyse:  flight_phases(topics) -> keep in-air or armed rows -> rules -> findings, penalty
          rule:  (findings, penalty) ; score = max(0, 100 - sum of penalties)
          nothing usable -> _skip(reason)   (PR-027..PR-030 fixed in issue 1)
```

Each rule returns its findings and its penalty, so the module score is the sum of what fired. The
weights (GPS 15, battery 15, motors 5, parameters 5, power 0) live on the classes and are read by the
score calculator of the report item.

## 3 Thresholds

| Check | Threshold | Value | LLR |
|---|---|---|---|
| GPS | HDOP warning / critical, sustained 2 s | 2.0 / 4.0 | 036 |
| GPS | Satellite drop within 5 s | 4 satellites | 035 |
| GPS | Fix loss counted from | 1.0 s | 033 |
| GPS | Jamming indicator warning / critical, sustained 2 s | 100 / 180 | 037 |
| Battery | Sag per cell warning / critical | 0.50 / 1.00 V | 049 |
| Battery | Pack temperature warning | 60 deg C | 052 |
| Battery | C-rate warning | 30 C | 050 |
| Battery | Capacity fade: drawn charge above rated x | 1.15 | 051 |
| Motors | RPM imbalance warning / critical | 8 % / 15 % | 059 |
| Motors | Current imbalance at hover | 20 % | 060 |
| Motors | ESC temperature warning | 80 deg C | 061 |
| Motors | Dropout (`STOPPED_RPM`, `OTHERS_FLYING_RPM`, `RPM_DROPOUT_MS`) | 100 rpm, 1000 rpm, 100 ms | 062 |
| Power | 5 V rail outside | 4.3 to 5.8 V | 067 |
| Parameters | Firmware range and recommended range | per parameter, from the tables | 079..082 |

Sources: the GPS, battery and motor numbers are engineering choices of the code's author, not taken from a
cited standard; the parameter limits come from the firmware metadata the generator downloads. No source or
retrieval date is recorded per value (OI-006).

## 4 Error handling

An exception inside a check never stops the run: `safe_analyse` turns it into a skipped result naming the
error (HLR-ANL-003). Missing inputs give a skipped result with the missing topic or column (LLR-ANL-003,
004). A frame with nothing any rule can read is a skip, not a clean 100 (LLR-ANL-042, 054, 064, 087).

## 5 Resource use and limits

All checks run in the default thread pool at the same time (LLR-INT-055); each works on frames already in
memory and downsamples chart data to bounded lengths (LLR-ANL-014).

## 6 Known gaps and deviations

| Gap | Reference |
|---|---|
| No common check bounds a recommended parameter value inside the firmware range | PR-009, PR-031 |
| Nearest firmware table used with no limit on the distance; merged table keeps a maximum from one release | PR-032 |
| A plugin without `name` stops the loader | PR-033 |
| `eph` judged with HDOP thresholds when `hdop` is absent | PR-034 |
| Power flags with every voltage on USB or NaN give a clean result | PR-035 |
| README describes GPS sustain times that differ from the code | PR-036 |
| A plugin's weight is added unscaled | PR-037 |
| Battery: negative current gives negative consumed charge; whole log used, not the flight windows | PR-028 (open part) |
