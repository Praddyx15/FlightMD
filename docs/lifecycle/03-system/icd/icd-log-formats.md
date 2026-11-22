# ICD: log files

FMD-ICD-LOG, issue 1, 2026-11-22.

The interface between whatever recorded a flight (autopilot, ground station, phone app) and the `intake` and
`parsers` items: which files are accepted, how each is recognised, and what is read from it. As built.
Requirements: HLR-INT-001 to 008, `hlr-prs.sdoc`; detail in LLR-INT-001 to 022 and `llr-prs.sdoc`. The
outside formats are defined by their owners; nothing here restates them beyond what the code relies on.

## 1 Accepted files

Recognition is by content first; the file name only decides between candidates the content cannot settle
(LLR-INT-001 to 011). Only the first 4096 bytes are read for this.

| Format id | Recorder | Recognised by | Parser | Notes |
|---|---|---|---|---|
| `px4_ulog` | PX4 flight controller | first 7 bytes `ULog\x01\x12\x35` | `ULogParser` (pyulog) | Any name |
| `ardupilot_bin` | ArduPilot dataflash, binary | `0xA3 0x95 0x80` and a valid FMT name | `ArduPilotBinParser` (pymavlink) | Any name |
| `betaflight_bbl` | Betaflight, INAV, Cleanflight blackbox | the blackbox start line anywhere in the header | `BetaflightParser` (own decoder) | Data versions 1 and 2 |
| `ardupilot_log` | ArduPilot dataflash, text | text starting `FMT,` with the expected fields, no zero byte | `ArduPilotTextParser` | Any name |
| `mavlink_tlog` | Ground station telemetry (QGroundControl, Mission Planner) | 3 records of 8-byte timestamp + MAVLink 1 or 2 frame; a short file whose first record is cut off only with the `.tlog` extension | `MavlinkTelemetryParser` (pymavlink) | |
| `dji_txt` | DJI phone app flight record | version byte 1 to 20 at offset 10 and three well-formed records; undecided headers only with `.txt` | `DJIParser` (own decoder) | Versions 13 and later need the key exchange of section 3 |
| `dji_dat` | DJI aircraft `.DAT` | `BUILD` at offset 16 or `LOGH` at offset 0 | none | Refused with the fixed text `DAT_UNSUPPORTED` |

A gzip file, or a zip holding exactly one file, is unpacked first, with size and ratio caps, into a private
directory, and the content inside is recognised the same way (LLR-INT-013 to 022). Anything else is refused
with `UnsupportedFormatError`, a `ValueError` whose text says what was expected (LLR-INT-010).

## 2 What is read

Each parser maps its format onto PX4 topic and column names, microseconds from the start of the log and PX4
units (`06-design/lld-prs.md`, section 3). The topics the analysers use are those named in their declared
inputs (`llr-anl.sdoc`, `llr-dyn.sdoc`). Fields the code does not name are ignored. Every conversion factor
is in an LLR of `llr-prs.sdoc`.

| Format | Arming state from | Flight mode from | Parameters from |
|---|---|---|---|
| ULog | `vehicle_status.arming_state` | `vehicle_status.nav_state` | ULog parameters |
| Dataflash | ARM messages, else EV 10 and 11 | MODE messages | PARM through the reader |
| Telemetry log | HEARTBEAT `base_mode` bit 128 | HEARTBEAT custom mode | PARAM_VALUE |
| Blackbox (Betaflight 3.5 and later) | arm switch flag and disarm events | angle and horizon switch flags | numeric header lines |
| DJI | motors-on bit of OSD | OSD flight mode | none |

## 3 DJI key exchange

For a DJI flight record of version 13 or later the parser sends one HTTPS POST to
`https://dev.dji.com/openapi/v1/flight-records/keychains` with the record's wrapped key material, the
auxiliary version and department numbers, and the developer key from `DJI_API_KEY` in the `Api-Key`
header; no flight data, position or file name. It follows no redirect, waits at most 30 s and reads at most
4 MiB of reply. With `FLIGHTMD_OFFLINE` set or no key, no request is made and the file is refused
(LLR-PRS-085 to 087; `icd-external-services.md`).

## 4 Limits

| Limit | Value | Set by |
|---|---|---|
| Log size on disk | `FLIGHTMD_MAX_LOG_MB`, default 512 MB | LLR-INT-041 |
| Unpacked size and compression ratio | caps in `compressed.py` | LLR-INT-019, 021 |
| Parse time | `FLIGHTMD_PARSE_TIMEOUT_S`, default 600 s | LLR-INT-037, 039 |
