# FMEA: key components

FMD-FMEA, issue 1, 2026-11-22. Failure modes of the components a result
depends on most, from the code as built and the low-level requirements of
every item. Effects point at the failure conditions of `hazard-assessment.md`.
Qualitative only: no failure rates. Not reviewed by a second person (OI-003).

Columns: **Local** is the effect inside the component, **System** the failure
condition it leads to, **Detection** how anyone finds out, **Now** what the
code already does, **Action** what is recommended (with the requirement,
problem report or open item that tracks it).

## Intake and pipeline

| Id | Component | Failure mode | Cause | Local | System | Detection | Now | Action |
|---|---|---|---|---|---|---|---|---|
| IN-01 | `detect_format` | Wrong format chosen | Bytes that satisfy another format's signature; a long undecided `.txt` taken as DJI on its extension | Wrong parser runs | FC-1.2 | Parser error, or "no analysable telemetry" | Content signatures; three consecutive frames for telemetry logs | PR-013 |
| IN-02 | `open_log` | Archive expands without bound, or holds something else | Crafted or damaged archive | Refused with a message | FC-1.1 | Error to the user | Byte cap, ratio cap, one-file rule, nested and unsafe paths refused | PR-012 for the unconverted error |
| IN-03 | Parser child process | Runs too long or dies | Huge or damaged log, out of memory | Stopped at the time limit; error | FC-1.1 | Error to the user | Timeout, exit-code message | - |
| IN-04 | Parse cache | Stale or wrong parse used | Parser changed without a cache version bump; entry renewed on every read | Old topics analysed by new rules | FC-2.1, FC-7.1 | None | Key is the log's SHA-256; version in the file name; expiry | PR-024; bump rule in `scmp.md` section 2 |
| IN-05 | Parse cache | Entry unreadable or planted | Crash while writing; another process writing the directory | Entry dropped and the log parsed again; or code runs on load | FC-1.1; security | Log warning; none for a planted file | Write beside and rename; every read or rebuild error drops the entry (PR-003 fixed, LLR-INT-029) | Keep the directory private (PY-D3); OI-011 |
| IN-06 | `_armed_windows`, `flight_phases` | Windows wrong or absent | No arming data; arming state mapped wrongly by a parser | Whole log treated as flight, or flight time left out | FC-3.1, FC-3.2 | Parse warning for the fallback; none for a wrong mapping | Fallback with a warning | Parser tests of the arming mapping per format |
| IN-07 | `_gps_track`, `_fill_path` | Path or figures wrong | Missing altitude or NaN position filled with 0; fast segments dropped; more than 500 points | A point at 0,0 or 0 m; distance and speed too low | FC-8.1 | A reader looking at the map | Implausible segments left out of the figures | PR-006, PR-007, PR-010 |
| IN-08 | Thread pool of checks | A check changes shared tables while others read them | A check that writes into a topic table in place | Another check reads altered data; result depends on timing | FC-4.1, FC-4.3 | None | Not examined | Review each check for in-place writes (OI-016) |

## Parsers

| Id | Component | Failure mode | Cause | Local | System | Detection | Now | Action |
|---|---|---|---|---|---|---|---|---|
| PA-01 | Any parser | Field mapped to the wrong column, or wrong scale or sign | Firmware changed a message; mapping error | Wrong numbers under a right name | FC-2.1 | Corpus (PX4, ArduPilot); otherwise none | Unit tests on built logs | State every factor in an LLR; real logs per format (OI-015) |
| PA-02 | Any parser | Messages or a time span dropped | Damaged or truncated log, unknown message version | Shorter or thinner topics | FC-2.2 | Parse warning: ULog dropouts and corruption, telemetry bad data and other senders, blackbox damaged frames, DJI damaged and undecrypted records | Counted and warned for those; the dataflash parsers drop rows with no time and add no warning (LLR-PRS-025, 048) | Add a dataflash warning for dropped rows |
| PA-03 | Clock handling | Timestamps wrong or not log-relative | Clock reset in the log, mixed time bases, boot time against GPS time | Windows and durations wrong; checks gate on the wrong samples | FC-2.1, FC-3.1 | Telemetry: warnings for receive-time fallback and reboots | Clock stated per format: LLR-PRS-004, 025, 053, 067, 081 | - |
| PA-04 | Arming and landed mapping | State mapped wrongly onto the PX4 numbering | Format-specific flags misread | Flight windows wrong | FC-3.1 | None | Mapping per format in LLR-PRS-015, 030, 031, 060, 074, 082, each with a test | Real logs per format (OI-015) |
| PA-05 | Metadata | Firmware version, vehicle type or start time wrong or missing | Field absent or in a new form | Wrong parameter table; no weather date | FC-6.3, FC-12.1 | Report shows what was read | Missing values stay empty | AN-06 |
| PA-06 | Telemetry-log parser | Another system's messages mixed in | Several systems on one link | Topics of two vehicles merged | FC-2.1 | Parse warning with the count ignored | Filtered to the busiest autopilot sender (LLR-PRS-052), tested | - |
| PA-07 | DJI parser | Encrypted record not decoded, or key requested when offline | Version 13 or later without a key; offline gate | Refused with a message, or records skipped | FC-1.1, FC-2.2 | Error to the user; warning with the count of undecrypted records | Offline and no-key refuse before any request (LLR-PRS-086); undecrypted records counted (LLR-PRS-087) | - |
| PA-08 | Blackbox decoder | Damaged frames accepted, or good frames rejected after a gap | Bit errors; logging paused | Spikes in the data, or a shortened log | FC-2.1, FC-2.2 | Warning with the count of skipped frames | A frame is believed only when the next one starts cleanly and its iteration and time jumps are inside limits (LLR-PRS-067) | - |
| PA-09 | Unit and scale choice by firmware version | Voltage, GPS altitude or gyro scale wrong for an unlisted firmware | Version not recognised | Wrong numbers | FC-2.1 | Warning for an unknown battery unit only | Battery left out when the unit is unknown (LLR-PRS-072) | Warn also for an unknown GPS altitude unit |
| PA-10 | DJI parser | Values from a record layout the code does not know | New app version | Wrong numbers, or records too short and dropped silently | FC-2.1, FC-2.2 | None for short records (LLR-PRS-088) | Fields read only when the record is long enough | Count short records in a warning |

## Checks and their framework

| Id | Component | Failure mode | Cause | Local | System | Detection | Now | Action |
|---|---|---|---|---|---|---|---|---|
| AN-01 | `BaseAnalyser.safe_analyse` | A check raises | Bug, unexpected column type | Result is a skip with the error text | FC-4.2 avoided | "Not assessed" with the reason in the report | Caught at the boundary (PY-D2); left out of the score | - |
| AN-02 | Any check | Returns a clean, assessed result with no usable data | Empty or all-NaN column, too few samples, sample rate too low for the band, nothing inside the flight windows | Module shows 100 | FC-3.2, FC-4.2, FC-4.4 | None | Skips where the check tests for it; GPS, battery, motors and parameters fixed for the cases of PR-027 to PR-030, with tests | Same review for the other checks |
| AN-03 | Any check | Threshold wrong for this vehicle | Threshold from one class of vehicle applied to another | Fault missed or invented | FC-4.1, FC-4.3 | Corpus review | Vehicle-aware advice; autopilot's own figures first | Record the source of each threshold (OI-006) |
| AN-04 | Any check | NaN reaches a severity decision or a score | Division by zero, empty slice | Comparison with NaN is false: no finding; or NaN score | FC-4.1, FC-5.1 | None | `clean` at report assembly; a NaN module score counts as 0 (PR-002 fixed) | PY-11 |
| AN-05 | Recommendation rules | Suggested value wrong or out of range | Current value zero or missing; percentage change with no bound | Entry on the change sheet | FC-6.1 | A reader comparing with the firmware documentation | Non-finite values dropped; names by vehicle | PR-009; SAF-008 |
| AN-06 | Parameter check | Wrong or no table for the firmware | Version not held; version string not understood | Ranges of another version applied, or check skipped | FC-6.3 | To establish | To establish from the analyser LLR | Report which table was used |
| AN-07 | Plugin | Fails to load, wrong type, name clash, or adds weight | Third-party code | Left out with a log warning; or changes the score's weights | FC-5.1 (weights) | Log only for a rejected plugin | Rejected plugins cannot stop an analysis | Say in the report which plugins ran |

## Score, explanations and report

| Id | Component | Failure mode | Cause | Local | System | Detection | Now | Action |
|---|---|---|---|---|---|---|---|---|
| SC-01 | `ScoreCalculator.calculate` | Score counts what was not checked | Skipped or unassessed module included; one small module carries the whole score | Passing score | FC-5.1 | `assessed_fraction`, shown in the PDF since PR-004 | Skipped and unassessed left out; "Not assessed" when none; NaN counts as 0 (PR-002 fixed) | PR-022 |
| RP-01 | `ExplanationEngine` | Text says more than the data | Fixed template wording; fallback text | Explanation not supported by the finding | FC-6.4 | A reader comparing with the technical summary | Keyed on rule identifier | PR-014, PR-020 |
| RP-02 | `ReportBuilder._deduplicate_params` | A recommendation lost or contradicted | Two checks, one parameter | First (most severe) kept; conflict written on the entry | FC-6.2 | The note on the entry | As described | Web application to show the note before download |
| RP-03 | AI summary | Summary misstates the findings | Model output | Summary string replaced | FC-10.1 | None for the reader | Numbers of the original must survive; findings untouched | PR-005; mark AI text in the report |
| RP-04 | PDF | Shows clean when nothing was assessed; omits warnings | Template logic | Misleading page | FC-4.2, FC-8.1 | Grade, assessed share and parse warnings printed | Not-assessed log and modules shown as such (PR-004 fixed, LLR-RPT-064) | PR-019, PR-021 |
| RP-05 | GPX, KML | Altitude or position wrong | Altitude mode; zero-filled values | Track drawn wrongly | FC-8.1 | A reader | Coordinate order correct; XML escaped | PR-007, PR-008 |

## Service and web application

| Id | Component | Failure mode | Cause | Local | System | Detection | Now | Action |
|---|---|---|---|---|---|---|---|---|
| ST-01 | Report store | Wrong report for an identifier, or a report changed after storing | Dedupe key, label collision, post-processing | Another flight's report served | FC-7.1 | Report names its input | Random identifiers; SHA-256 dedupe; stored report not rewritten (LLR-API, tested) | - |
| ST-02 | Expiry | Report gone, or served after expiry | Timer, restart, disk wiped | Lost or stale report | FC-7.3 | User | Stated in the README | - |
| ST-03 | Tune-fly-verify | "Finding gone" when the check did not run in the later flight | Later log lacks the module's inputs | False confidence in a fix | FC-9.1 | None | As stated in `llr-api.sdoc` (parameter changes) | Verdict to need the module assessed in the later flight |
| ST-04 | Alert webhook | Not delivered | Receiver down, address refused | Nothing sent | FC-9.2 | Log only | Does not fail the analysis | Show delivery state on the airframe page |
| WB-01 | Units | Value shown in the wrong unit or converted twice | Conversion error | Misreading | FC-11.1 | Unit tests | All conversions in `lib/units.ts` and the formatters of `lib/format.ts`, with tests (LLR-WEB) | - |
| WB-02 | Report view | Not-assessed shown as healthy; warnings hidden | Colour or layout; raw score shown | Misreading | FC-11.1 | None | Report page and score circle use `isAssessed`; airframe, comparison and change records still show the raw 0 | PR-042 |
| WB-03 | Parameter file | Value rounded or formatted so the ground station reads another number; conflict note not shown | Number formatting; integer or float type guessed | Wrong value loaded | FC-6.1, FC-8.1 | Unit tests of the file writers | Values written by `fmtParam` | PR-039, PR-040 |
| ST-05 | Airframe claim | Airframe claimed by a token nobody holds | Queue hand-over fails after the claim | Owner locked out | FC-9.1 | User | 503 to the caller | PR-043 |
| ST-06 | Maintenance status | "Hours OK" when maintenance is due | Hours counted by upload time | Maintenance missed | FC-9.1 | None | - | PR-046 |
| ST-07 | Question endpoint | Report sent to an AI provider in offline mode | No offline check | Data leaves the host | FC-12.1 | None | Needs a configured key | PR-023 |
