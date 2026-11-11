# Report schema changelog

`FlightMDReport.schema_version`. Every change so far is additive: a reader
written for an older version can read a newer report by ignoring fields it
doesn't know. The JSON Schema for each published version is
`flightmd-report-<version>.json` next to this file (1.7 is the first one
published; earlier versions are only described here).

To change the schema: edit `flightmd_core/models/`, bump `schema_version`,
run `python scripts/export_schema.py`, add a section here.
`tests/test_schema.py` fails until the published file matches the model.

## 1.7

- `Finding.params: list[str]`: every parameter the finding's recommendation
  touches, including the ones in `param_changes`. Used to match a finding to
  parameter changes applied afterwards (tune, fly, verify). Reports older than
  1.7 get it filled from `param_changes` when loaded.
- `FlightMDReport.generated_at`: ISO-8601 UTC time the report was built.
- `FlightMetadata.log_sha256`, `source_format`, `planning_brief_sha256`,
  `gps_path_t_s` (per-point log-relative seconds, same length as `gps_path`).
- `airframe_name` is now filled for PX4 (SYS_AUTOSTART) and ArduPilot
  (FRAME_CLASS / FRAME_TYPE).
- New `Finding.kind` values: `vibration.imu_errors`, `ekf.innovation_ratio_high`,
  `ekf.filter_fault`, `ekf.sensor_timeout`, `params.arming_checks_off`,
  `power.vcc_out_of_range`, `power.overcurrent`. New analyser `power`
  (weight 0). `params.deprecated` is no longer produced.
- Vibration `chart_data` from the autopilot's own metric carries `vibe`,
  `warn`, `crit` (and `metric` for PX4) instead of raw `x/y/z`.

## 1.6

- `AnalyserResult.assessed` (false = the module couldn't check anything; not
  the same as a clean 100).
- `FlightMDReport.assessed_fraction`: share of the score weight assessed.
- `Finding.t_start_s` / `t_end_s` (seconds; the ms pair is kept),
  `Finding.kind`, `Finding.confidence_level`.
- `FlightMetadata.armed_windows`, `parse_warnings`.
- `overall_score` is 0 with `score_label` "Not assessed" and `letter_grade`
  "-" when nothing could be assessed.

## 1.5

- `FlightMetadata.location_name` (reverse-geocoded place name).

## 1.4

- `Category.ASCENT_PROFILE` and the `ascent_profile` analyser (unweighted).
- `FlightMetadata.gps_path_wind_speed_ms` and `gps_path_hdop` (landed just
  before this bump, under 1.3).

## 1.3

- `AnalyserResult.key_metrics: dict[str, float]`, headline numbers whether or
  not a finding fired.

## 1.2

- `FlightMDReport.letter_grade`.
- `FlightMetadata.weather`, `gps_path`.
- Removed `claude_model_findings` / `claude_model_summary`: findings and
  summary are rule-based now. (1.1 was never released.)

## 1.0

- First release.
