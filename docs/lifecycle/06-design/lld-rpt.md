# Report low-level design

FMD-LLD-RPT, issue 1, 2026-11-20.

As built. Requirements: `05-requirements/hlr-rpt.sdoc`, `05-requirements/llr-rpt.sdoc`. Interfaces:
`03-system/icd/icd-report-and-exports.md`, `03-system/icd/icd-external-services.md`.

## 1 Purpose and code

The report item holds the report data model, turns module results into a score, explanations, a summary and
one report object, and writes the exports. It also holds the three functions that reach outside services.

| File | Contents |
|---|---|
| `flightmd_core/models/findings.py` | `Severity`, `Category`, `ParamRecommendation`, `Finding`, `AnalyserResult`, `FlightMDReport` (pydantic) |
| `flightmd_core/models/metadata.py` | `FlightMetadata`, `utc_iso`, `MIN_EPOCH_US` |
| `flightmd_core/models/__init__.py`, `services/__init__.py` | Re-exports |
| `services/score_calculator.py` | `ScoreCalculator`, `BANDS`, not-assessed label and grade |
| `services/explanation_engine.py` | `TEMPLATES` (42 kinds), `CATEGORY_FALLBACK`, `ExplanationEngine` |
| `services/report_builder.py` | `ReportBuilder`: sanitise, sort, change sheet, report fields |
| `services/ai_enhancer.py` | `AIEnhancer`, `clean_text`, `numbers_kept`, `SYSTEM_PROMPT` |
| `services/weather_lookup.py` | `fetch_weather` (Open-Meteo) |
| `services/geocoding.py` | `reverse_geocode` (Nominatim) |
| `services/airframes.py` | `px4_airframe`, `ardupilot_frame` and their tables |
| `services/geo_export.py` | `generate_gpx`, `generate_kml` |
| `exporters/pdf.py`, `exporters/templates/*.html` | Report PDF and airframe record PDF |
| `scripts/export_schema.py` | Writes `docs/schema/flightmd-report-<version>.json` |

## 2 Structure and data flow

The orchestrator (another item) calls this item in the order below. Nothing here calls the orchestrator.

```
parsers ----------> px4_airframe / ardupilot_frame, utc_iso      LLR-RPT-012, 056 to 058
                    (fill FlightMetadata.airframe_name, log_start_utc)

run_analysis
  |  not offline and a position:
  |-- fetch_weather(lat, lon, log_start_utc) -> metadata.weather  LLR-RPT-052 to 055
  |-- reverse_geocode(lat, lon) -> metadata.location_name         LLR-RPT-050, 051
  |  analysers run -> list[AnalyserResult]                        LLR-RPT-008, 009
  |-- ScoreCalculator().calculate(results)                        LLR-RPT-014 to 018, 020
  |       -> (score, label, grade); marks skipped as unassessed
  |-- ExplanationEngine.explain_findings(findings)                LLR-RPT-028 to 031
  |-- ExplanationEngine.generate_summary(...)                     LLR-RPT-032 to 034
  |  configured and not offline:
  |-- AIEnhancer.polish_summary(summary, findings, metadata)      LLR-RPT-040 to 044
  |       -> summary text only
  `-- ReportBuilder().build(...)                                  LLR-RPT-021 to 027
          sanitise findings, results, metadata  (021 to 023)
          sort findings                         (024)
          change sheet                          (025, 026)
          report_id, generated_at, assessed_fraction (019, 027)
          -> FlightMDReport                     (001 to 011)

API / command line, from a finished report:
  generate_gpx(report), generate_kml(report)                      LLR-RPT-045 to 049
  render_report_pdf(report)                                       LLR-RPT-059 to 064
  render_airframe_record_pdf(...)                                 LLR-RPT-065
  AIEnhancer.complete(prompt, max_tokens, system)   (questions)   LLR-RPT-038, 039

scripts/export_schema.py -> docs/schema/flightmd-report-1.7.json  LLR-RPT-066
```

The AI call sits between the summary and the build and receives the findings list, but writes to nothing it
is given; its only output is the returned string.

## 3 Data

| Name | Value | Unit | Where used |
|---|---|---|---|
| `schema_version` default | `"1.7"` | - | `FlightMDReport`, schema file name |
| Finding time window | `timestamp_start_ms`/`_end_ms`, `t_start_s`/`t_end_s` | ms, s, log-relative | `Finding` |
| Confidence levels | high at 0.75, medium at 0.4, else low | 0 to 1 | `Finding._fill_derived` |
| `Finding.id` default | first 8 characters of a UUID4 | - | `Finding` |
| `MIN_EPOCH_US` | 1262304000000000 | us since epoch | parsers (clock never set below it) |
| UTC text form | `%Y-%m-%dT%H:%M:%SZ` | whole seconds | `utc_iso`, `generated_at`, `log_start_utc` |
| `BANDS` | 90 A Excellent, 80 B Good, 70 C Caution, 60 D Caution, 50 E Warning, 0 F Critical | score floor | label and grade |
| Not assessed | 0.0, `Not assessed`, `-` | - | `calculate` |
| Overall score rounding | 1 decimal place | - | `calculate` |
| `assessed_fraction` rounding | 3 decimal places | 0 to 1 | `assessed_fraction` |
| Module weights | from `module_weights()`; built-ins sum to 100 | - | `ScoreCalculator` |
| `SEVERITY_PENALTY` | 30, 15, 5, 0 | points | defined, not used in this item |
| `SEVERITY_ORDER` | critical 0, warning 1, info 2, good 3 | - | sort key |
| AI timeout, retries | 30.0, 2 | s, count | provider clients |
| AI prompt limits | 15 findings, title 120, summary 1500, reply 300 tokens | chars, tokens | `polish_summary` |
| `clean_text` default limit | 300 | chars | prompts |
| Weather and geocoding timeout | 2.0 | s per request | `urlopen` |
| Weather position precision | 4 decimal places | degrees | Open-Meteo query |
| Geocoding position precision, zoom | 5 decimal places, 10 | degrees, - | Nominatim query |
| Wind conversion | km/h divided by 3.6, 2 decimals | m/s | `fetch_weather` |
| `gps_path` point | `[lat, lon, alt]` | degrees, degrees, m | exports |
| GPX and KML precision | 7 places, 2 places | degrees, m | exports |
| Export time | `log_start_utc` + `gps_path_t_s`, milliseconds | UTC | exports |
| PDF page | A4, margins 20/18/24/18 | mm | `BASE_CSS` |
| `SCORE_COLOURS` floors | 90, 75, 60, 40, 0 | score | PDF only |

## 4 Error handling

| Where | What happens |
|---|---|
| `Finding` validation | Non-finite confidence becomes 0.0; no error |
| `ScoreCalculator.calculate` | Raises nothing. No weighted assessed module gives the not-assessed result |
| `ReportBuilder.build` | Non-finite numbers are replaced or dropped. A NaN left in `gps_path` or `gps_path_t_s` fails model validation and the error propagates; the orchestrator fills path NaN with 0.0 first |
| `ExplanationEngine` | Raises nothing by design; the orchestrator wraps it and has its own fallback text |
| `AIEnhancer.__init__` | Missing client library: warning, enhancer stays unconfigured |
| `AIEnhancer.complete` | `RuntimeError` when unconfigured; provider errors propagate |
| `AIEnhancer.polish_summary` | Catches every `Exception`, logs a warning, returns the rule-based summary. Swallowed so the optional layer cannot fail a report |
| `fetch_weather` | Every request error is logged and swallowed; result is the "unavailable" dict |
| `reverse_geocode` | Every request or decode error is logged and swallowed; result is None |
| `px4_airframe`, `ardupilot_frame` | Bad or missing values give None; a missing data file raises |
| `generate_gpx`, `generate_kml` | A `log_start_utc` not in the expected form raises `ValueError`; nothing is caught |
| `template_env`, `_write_pdf` | `RuntimeError` with the install hint when Jinja2, WeasyPrint or its system libraries are missing |
| `export_schema.py` | Writes to a `.tmp` file and replaces, so a failed run leaves the old file |

## 5 Resource use and limits

- Scoring, explanation and assembly are linear in the number of findings and results and hold no state
  between reports. `ReportBuilder.build` makes a second `ScoreCalculator` for `assessed_fraction`.
- Network: at most two Open-Meteo requests and one Nominatim request per report, 2.0 s each, run one after
  the other, so up to about 6 s. An AI call can take 30 s per attempt with 2 retries.
- AI prompt size is bounded by the limits in section 3.
- GPX and KML are built in memory; the path has at most 500 points (set by the orchestrator).
- PDF renders run one at a time under a process-wide lock. The Jinja2 environment and the PX4 airframe
  table are each loaded once and cached.

## 6 Known gaps and deviations

Numbers are in `10-configuration/problem-reports.md`.

| Problem report | Gap | Requirement that records it |
|---|---|---|
| PR-002 | Fixed in issue 1: a NaN module score was clamped to 100.0 in `calculate`; it now counts as 0 | LLR-RPT-020 |
| PR-004 | Fixed in issue 1: the PDF printed "No significant issues detected" whenever findings were empty and read `skipped` only; it now shows not-assessed logs and modules, grade, assessed share and parse warnings | LLR-RPT-064 |
| PR-005 | `numbers_kept` accepts any rewrite of a summary with no digits and ignores added numbers; no field marks an AI-written summary | LLR-RPT-041, 043 |
| PR-008 | KML altitude mode is `relativeToGround` with GPS altitudes | LLR-RPT-048 |
| PR-017 | No limits-of-use statement in the report, PDF or exports | HLR-RPT-030 (Proposed) |
| PR-018 | Fixed in issue 1: PDF pages were headed "CONFIDENTIAL" and the footer carried a personal name | LLR-RPT-062 |
| PR-019 | Score banded at 1 decimal, printed with none; PDF colour floors differ from `BANDS` | LLR-RPT-033, 059 |
| PR-020 | `_explain` always overwrites `plain_english` | LLR-RPT-029 |
| PR-021 | PDF "Generated" is the render time; start time hidden at 0 ms | LLR-RPT-063, 064 |
| PR-022 | One low-weight assessed module can give 100 and grade A | LLR-RPT-015 |

Other deviations, not numbered here:

- The report has no engine version field (HLR-RPT-029, Proposed).
- `Finding.id` is random when the module sets none, so two runs on one log differ in more than the report
  identifier and times (HLR-RPT-031).
- A missing altitude reaches the exports as 0.0 m, because the orchestrator fills path NaN with 0.0; the
  "leave out a missing altitude" branch of `_alt` is then not reached for reports it builds (LLR-RPT-023,
  045).
- `log_start_utc` is whole seconds, so export times can be up to 1 s early.
- The weather, geocoding and AI functions do not read the offline setting; the caller must (HLR-RPT-026).
- `SEVERITY_PENALTY` and `NOT_CONFIGURED_MESSAGE` are defined and used by no code in the repository.
- Test `covers:` lines are in place for `test_score_calculator.py` and `test_report_builder.py` only; the
  other test files of this item are not yet tagged, so the trace check lists those requirements.
