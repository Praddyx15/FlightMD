# Log parsers low-level design

FMD-LLD-PRS, issue 1, 2026-11-22.

As built. Requirements: `05-requirements/hlr-prs.sdoc`, `05-requirements/llr-prs.sdoc`. Input formats:
`03-system/icd/icd-log-formats.md`. Short by intent: the LLR carry the unit conversions and numbers.

## 1 Purpose and code

Each parser turns one log format into the same three things: a dict of PX4-named topics (pandas frames
with a `timestamp` column in microseconds from the start of the log), a dict of parameters (`name -> float`)
and a `FlightMetadata`. The analysers only ever see that shape.

| File | Parser | LLR |
|---|---|---|
| `flightmd_core/services/ulog_parser.py` | `ULogParser`, PX4 ULog through pyulog | LLR-PRS-001..018 |
| `flightmd_core/services/ardupilot_parser.py` | `ArduPilotBinParser`, binary dataflash through pymavlink `DFReader` | LLR-PRS-019..048 |
| `flightmd_core/services/ardupilot_text_parser.py` | `ArduPilotTextParser`, the same with the text reader | LLR-PRS-049 |
| `flightmd_core/services/mavlink_telemetry_parser.py` | `MavlinkTelemetryParser`, ground station `.tlog` through pymavlink | LLR-PRS-050..063 |
| `flightmd_core/services/betaflight_parser.py` | `BetaflightParser`, own blackbox decoder | LLR-PRS-064..075 |
| `flightmd_core/services/dji_parser.py` | `DJIParser`, own DJI flight record decoder | LLR-PRS-076..089 |
| (both of the last two) | Content checks used by format detection | LLR-PRS-090 |

## 2 Structure and data flow

```
format_detector.detect_format -> PARSERS[name]() -> parser.parse(path[, progress])
                                                     |
             read records (library or own decoder)   |  BAD_DATA / damaged frames counted
             group by message family and instance    |  ColumnBuffer rows (dataflash, tlog)
             one clock, relative to the first sample |  LLR-PRS-004, 025, 053, 067, 081
             rename and rescale to PX4 topics        |  store_instances: name, name_1, ...
             arming, nav_state, landed               |  vehicle_status, vehicle_land_detected
             parameters, metadata, parse_warnings    v
                                   (topics, params, FlightMetadata)
```

The dataflash and telemetry parsers share `store_instances`, `merge_esc`, `ardupilot_nav_state` and the
`BOARD_LINE` and firmware-banner tables of `ardupilot_parser.py`. The telemetry parser keeps one sending
system (LLR-PRS-052) before anything else, so a ground station or gimbal on the same link never mixes in.

## 3 Data

- Clock: microseconds, int64, relative to the earliest sample of the log. The telemetry log uses vehicle
  boot time shifted onto the receive clock per boot segment (LLR-PRS-053); the blackbox clock unwraps the
  32-bit rollover (LLR-PRS-067); DJI has no per-record time and uses the OSD record index x 100 ms
  (LLR-PRS-081).
- Units follow PX4: rad/s, m/s^2, degrees x 1e7, millimetres for GPS altitude, volts and amperes. Each
  conversion factor is in an LLR (RS-18 does not apply; no threshold lives here).
- `parse_warnings` is the only channel for "the data was incomplete". The dataflash parsers add none
  (HLR-PRS-013).

## 4 Error handling

A missing file raises `FileNotFoundError`; a file a parser cannot read raises `ValueError` with a sentence
the user can act on (LLR-PRS-064, 076); errors from pyulog and pymavlink pass up unchanged. The intake item
turns all of these into the refusal of LLR-INT-039 and LLR-INT-045. Damaged records inside a readable file
are skipped and counted, never guessed (LLR-PRS-063, 067, 078).

## 5 Resource use and limits

Parsers read the whole file into memory (blackbox, DJI) or stream it through the library (others). Size and
time limits are set outside the parsers by the intake item (HLR-PRS-006; LLR-INT-037, 041). The only
network use is the DJI key exchange for version 13 and later records, off when offline or without a key
(LLR-PRS-085, 086).

## 6 Known gaps and deviations

| Gap | Where | Reference |
|---|---|---|
| The DJI parser reads no firmware version and always says `vehicle_type` "Copter" | `dji_parser.py` | LLR-PRS-089 |
| Betaflight accelerometer z reads +1 g at rest, PX4 -1 g; the analysers high-pass it | `betaflight_parser.py` | LLR-PRS-070 |
| Blackbox battery voltage is left out for Cleanflight and Betaflight before 3.1 (raw ADC counts) | `betaflight_parser.py` | LLR-PRS-072 |
| The dataflash parsers report no parse warnings at all, also for rows dropped for a missing time | `ardupilot_parser.py` | LLR-PRS-025, 048 |
| A parser may emit NaN positions, which then reach the path as 0,0 | intake | PR-007 |
| No real logs for Betaflight, INAV, DJI or text dataflash in the corpus | `tests/corpus/` | OI-015 |
