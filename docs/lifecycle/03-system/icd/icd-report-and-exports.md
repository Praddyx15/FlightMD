# ICD: report and exports

FMD-ICD-RPT, issue 1, 2026-11-20.

What leaves the engine as a result: the report (a `FlightMDReport`, as a Python object or as JSON) and the
GPX, KML and PDF made from it. Direction is always engine to consumer. Facts are from the code as built.
Governing requirements: HLR-RPT-001 to 020 and 031.

## 1 Consumers

| Consumer | Takes |
|---|---|
| Web application | Report JSON from the API; export files |
| API | The report object: stores it, serves JSON (header `X-FlightMD-Schema-Version`), builds exports, compares reports, builds AI question prompts |
| Command line | The report object: writes JSON, GPX, KML, PDF |
| Other programs (named in the model's own notes: UAOP, AirBrief) | The Python package or the JSON; they check `schema_version` |

## 2 Report JSON

UTF-8 JSON. Every number is finite; a value that could not be computed is `null` or absent from a map.
Times inside a log are log-relative.

### 2.1 Top level (`FlightMDReport`)

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `report_id` | string | - | UUID4 set at assembly; the API replaces it with the job's identifier |
| `schema_version` | string | - | `"1.7"` |
| `overall_score` | number | 0 to 100, 1 decimal | Weighted mean of assessed modules; 0 when nothing was assessed |
| `score_label` | string | - | Excellent, Good, Caution, Warning, Critical, or `Not assessed` |
| `letter_grade` | string | - | A to F, or `-` when not assessed |
| `executive_summary` | string | - | Rule-based text, or its AI rewording when an AI provider is configured. No field says which |
| `metadata` | object | - | `FlightMetadata`, 2.5 |
| `findings` | array | - | All findings, most severe first, then by confidence |
| `param_change_sheet` | array | - | `ParamRecommendation`, at most one per parameter |
| `analyser_results` | array | - | `AnalyserResult`, one per module, each with its own findings |
| `processing_time_ms` | integer | ms | Wall time of the analysis |
| `file_name` | string | - | As given by the caller |
| `file_size_bytes` | integer | bytes | As given by the caller |
| `assessed_fraction` | number or null | 0 to 1, 3 decimals | Share of the scoring weight that was assessed |
| `generated_at` | string or null | UTC | `YYYY-MM-DDTHH:MM:SSZ`; null in reports older than 1.7 |

### 2.2 `Finding`

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `id` | string | - | 8 characters, random unless the module set it |
| `category` | string | - | oscillation, vibration, ekf, battery, gps, parameters, motors, ascent_profile, system |
| `severity` | string | - | critical, warning, info, good |
| `title` | string | - | Display text |
| `technical_summary` | string | - | Measured values |
| `plain_english` | string | - | Template text for the `kind`, else the technical summary |
| `recommendation` | string | - | The module's action text, else a fallback |
| `confidence` | number | 0 to 1 | Held to the range; non-finite becomes 0 |
| `confidence_level` | string or null | - | high (0.75 and up), medium (0.4 and up), low |
| `timestamp_start_ms`, `timestamp_end_ms` | integer or null | ms | Window, log-relative |
| `t_start_s`, `t_end_s` | number or null | s | Same window in seconds |
| `chart_data` | object or null | - | Free-form data for charts; keys depend on the module |
| `param_changes` | array | - | `ParamRecommendation` of this finding |
| `kind` | string or null | - | Stable rule identifier, for example `gps.fix_lost` |
| `params` | array of string | - | Every parameter the finding touches, including those in `param_changes` |

### 2.3 `ParamRecommendation`

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `param_name` | string | - | Parameter name as the autopilot uses it |
| `current_value` | number | parameter's own | Value in the log; always finite |
| `suggested_value` | number | parameter's own | Suggested value; always finite |
| `unit` | string or null | - | Unit text when the module knows it |
| `change_direction` | string | - | `increase`, `decrease` or `set` (not checked by the model) |
| `reason` | string | - | One line; on the sheet may end with a conflict note and "Review before changing." |

### 2.4 `AnalyserResult`

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `analyser` | string | - | Module name, the key of its weight |
| `display_name` | string | - | Name for people |
| `findings` | array | - | This module's findings, in the module's order |
| `health_score` | number | 0 to 100 | Meaningful only when `assessed` is true; default 100 |
| `skipped` | boolean | - | Inputs missing or the module failed |
| `skip_reason` | string or null | - | Why; an error reads `Analysis error: ...` |
| `processing_ms` | integer | ms | Time the module took |
| `key_metrics` | map of string to number | per metric | Headline numbers; non-finite ones are dropped |
| `assessed` | boolean | - | False when the module could check nothing; always false when skipped |

### 2.5 `FlightMetadata`

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `duration_seconds` | number | s | Log length; 0 when unknown |
| `firmware_version`, `px4_version`, `hardware_id` | string or null | - | From the log |
| `airframe_id` | integer or null | - | PX4 `SYS_AUTOSTART` |
| `airframe_name`, `vehicle_type` | string or null | - | From the parameters |
| `log_start_utc` | string or null | UTC, whole seconds | Time of the log's start; null when the log cannot tell |
| `arm_count` | integer | - | Number of arming events |
| `flight_modes_used`, `available_topics` | array of string | - | From the log |
| `max_altitude_m` | number or null | m | Above the first altitude sample when taken from the GPS track |
| `max_speed_ms` | number or null | m/s | |
| `total_distance_m` | number or null | m | |
| `weather` | object or null | - | `temperature_max_c`, `temperature_min_c` (deg C), `wind_speed_max_ms` (m/s), `rain_sum_mm` (mm), `description`; values null with the reason in `description` when not looked up |
| `location_name` | string or null | - | Town-level place name |
| `gps_path` | array of `[lat, lon, alt]` or null | degrees, degrees, m | At most 500 points; a missing altitude is written 0.0 |
| `gps_path_t_s` | array of number or null | s, log-relative | One per path point |
| `gps_path_hdop`, `gps_path_wind_speed_ms` | array of number or null entries | -, m/s | One per path point; null where no reading |
| `armed_windows` | array of `[start_s, end_s]` or null | s, log-relative | null when the log has no arming data |
| `parse_warnings` | array of string | - | What was skipped, assumed or fell back |
| `log_sha256` | string or null | hex | SHA-256 of the file as uploaded |
| `source_format` | string or null | - | Detector identifier, for example `px4_ulog` |
| `planning_brief_sha256` | string or null | hex | Set by the API when given at upload |

### 2.6 Versioning

- `schema_version` is a field default in the model. A change to the models means: bump it, run
  `scripts/export_schema.py`, add a section to `docs/schema/CHANGELOG.md`.
- The published schema is `docs/schema/flightmd-report-<version>.json`. 1.7 is the first one published.
  `tests/test_schema.py` fails while the published file differs from the model or the changelog lacks the
  version.
- Every change so far is additive: a reader for an older version reads a newer report by ignoring unknown
  fields, and the current model loads older reports (new fields are optional or defaulted).

| Version | Change |
|---|---|
| 1.7 | `Finding.params`; `generated_at`; `log_sha256`, `source_format`, `planning_brief_sha256`, `gps_path_t_s`; `airframe_name` filled; new kinds and the `power` module |
| 1.6 | `assessed`, `assessed_fraction`; `t_start_s`, `t_end_s`, `kind`, `confidence_level`; `armed_windows`, `parse_warnings`; the not-assessed score |
| 1.5 | `location_name` |
| 1.4 | `ascent_profile` category and module; `gps_path_wind_speed_ms`, `gps_path_hdop` |
| 1.3 | `key_metrics` |
| 1.2 | `letter_grade`; `weather`, `gps_path`; AI finding fields removed |
| 1.0 | First release |

The report carries no engine version (HLR-RPT-029, Proposed).

## 3 GPX export

`generate_gpx(report)` returns bytes: an XML declaration and a GPX 1.1 document, UTF-8.

| Element or attribute | Value |
|---|---|
| `gpx` | `version="1.1"`, `creator="FlightMD"`, namespace `http://www.topografix.com/GPX/1/1` |
| `trk/name` | `file_name`, XML-escaped |
| `trk/trkseg/trkpt` | One per `gps_path` point, in path order |
| `trkpt@lat`, `trkpt@lon` | Decimal degrees, 7 decimal places |
| `trkpt/ele` | Altitude in m, 2 decimal places; the `gps_path` value as it is. Left out only when the value is absent or not finite |
| `trkpt/time` | UTC, `YYYY-MM-DDTHH:MM:SS.mmmZ` = `log_start_utc` + `gps_path_t_s`. Written only when `log_start_utc` exists and `gps_path_t_s` has one entry per point |

No path gives a document with an empty `trkseg`. No waypoints, routes, speed or extensions are written.

## 4 KML export

`generate_kml(report)` returns bytes: an XML declaration and a KML 2.2 document, UTF-8.

| Element | Value |
|---|---|
| `kml` | Namespace `http://www.opengis.net/kml/2.2` |
| `Document/name` | `file_name`, XML-escaped |
| `Placemark/name` | `Flight Path` |
| `LineString/altitudeMode` | `relativeToGround` |
| `LineString/extrude` | `1` |
| `LineString/coordinates` | `lon,lat,alt` per point, space separated; degrees to 7 places, m to 2 places; altitude 0 when absent |
| `Folder` "Path points" | Only when the path is not empty and per-point time, HDOP or wind exists; `visibility` 0 |
| `Folder/Placemark/TimeStamp/when` | UTC time of the point, as in GPX, when known |
| `Folder/Placemark/ExtendedData/Data` | `t_s` (s, log-relative), `hdop`, `wind_speed_ms` (m/s); a missing reading is left out |
| `Folder/Placemark/Point` | `altitudeMode` `relativeToGround`; `coordinates` `lon,lat,alt` |

The altitude written is a GPS altitude, not a height above ground (problem report PR-008).

## 5 PDF report

`render_report_pdf(report)` returns PDF bytes, A4. It needs the `pdf` extra; without it the call raises
`RuntimeError` naming `flightmd-core[pdf]`. All report text is HTML-escaped.

| Section | Data shown |
|---|---|
| Page header and footer | "Report" and the first 8 characters of `report_id`; footer "FlightMD · Page n of m" |
| Header | `report_id`, time of rendering (UTC, to the minute), `file_name`, size in KB, `overall_score` as an integer with `score_label` and the grade (a dash and "Not assessed" when the grade is "-"), and the assessed share of the scoring weight |
| Flight Information | Duration `MM:SS`, `arm_count`, `flight_modes_used`; when present `max_altitude_m` (m), `max_speed_ms` (m/s), `firmware_version`, `hardware_id`; processing time (s); `schema_version` |
| Executive Summary | `executive_summary` |
| Findings | Count; when there are none, a line that says whether nothing was assessed, part was assessed (with the share) or all was; per finding `severity`, `title`, `category`, `confidence` as a percentage, start time `MM:SS.t` when not 0, `plain_english`, `recommendation`, `technical_summary`, its `param_changes` |
| Parse Warnings | When there are any: each entry of `metadata.parse_warnings` |
| Parameter Change Sheet | When not empty: name, current, suggested, unit, direction, reason |
| Module Summary | Per module: `display_name`, Skipped, Not assessed or Ran, `health_score` only when assessed, finding count, `processing_ms`, `skip_reason` |
| Internal Review Record | Empty lines for reviewer, date, signature, site |
| Closing statement | Not a regulatory or compliance document; does not replace an engineer's judgement |

Not shown: `letter_grade`, `assessed`, `assessed_fraction`, `confidence_level`, `parse_warnings`, `weather`,
`location_name`, `log_sha256`, `generated_at`, the flight path. Open points on the PDF: problem reports
PR-004, PR-017, PR-018, PR-019, PR-021.

`render_airframe_record_pdf(...)` gives a second PDF from values the API passes (label, flights, maintenance
log, checklist, hours); it takes nothing from a report object (HLR-RPT-019).
