# System architecture

FMD-SA, issue 1, 2026-11-20. The items FlightMD is made of, what each is
responsible for, how they connect and which system requirements each carries.
As built at commit `50a1eba`. The software design inside the items is
`docs/lifecycle/06-design/`.

## 1. Items

| Item | Short | Kind | Code | Responsible for |
|---|---|---|---|---|
| `intake` | INT | Software | `flightmd_core/services/format_detector.py`, `compressed.py`, `columns.py`, `flightmd_core/cache.py`, `orchestrator.py`, `__main__.py`, `__init__.py` | Opening a log (archives, limits), identifying its format, the parse cache, running the pipeline in order with progress, armed windows and flight path, the command line and the library entry point |
| `parsers` | PRS | Software | `flightmd_core/services/ulog_parser.py`, `ardupilot_parser.py`, `ardupilot_text_parser.py`, `mavlink_telemetry_parser.py`, `betaflight_parser.py`, `dji_parser.py` | Turning each format into topics, parameters and metadata in one internal form, with warnings for what was skipped or guessed |
| `analysers` | ANL, DYN | Software | `flightmd_core/analysers/` | Flight phases, vehicle type, the nine checks, their findings, module scores and parameter recommendations; plugins |
| `report` | RPT | Software | `flightmd_core/models/`, `flightmd_core/services/score_calculator.py`, `report_builder.py`, `explanation_engine.py`, `ai_enhancer.py`, `geo_export.py`, `geocoding.py`, `weather_lookup.py`, `airframes.py`, `flightmd_core/exporters/` | The report model and schema, overall score, explanations, change sheet, exports, flight context, optional AI summary |
| `api` | API | Software | `api/` | Upload, jobs and progress, report storage and expiry, exports over HTTP, airframe history, tune-fly-verify, alerts, Q&A, rate limits, metrics |
| `web` | WEB | Software | `frontend/` | Upload page, report page, charts, map and 3D path, parameter sheet and file download, airframe pages, comparison, units and themes |
| `data` | - | Data | `flightmd_core/data/` | Firmware parameter tables, safe ranges, PX4 airframe names |
| `tools` | - | Software (not shipped in the service) | `scripts/`, `tools/trace.py`, `tools/walkthrough/` | Parameter table generator, schema export, sample-log generator, trace check, walkthrough recorder |
| `deployment` | - | Configuration | `api/Dockerfile`, `docker-compose.yml`, `api/render.yaml`, `frontend/vercel.json`, `.env.example` | Where the service runs and with which limits |
| `procedure` | - | People | `docs/lifecycle/01-plans/`, `09-reviews/` | Golden-result review, table regeneration review, release checks |

The engine is `intake` + `parsers` + `analysers` + `report` + `data`, shipped
as the Python package `flightmd-core`. The service is the engine + `api`. The
web application is separate and talks to the service over HTTP only.

## 2. Structure

```
                        +------------------ web (browser, Next.js server) ------------------+
                        |  upload | report | charts | map/3D | param sheet | airframe | diff |
                        +------------------------------+-------------------------------------+
                                                       | HTTP (icd-http-api.md)
+------------------------------------------------------v-------------------------------------+
| api   routers -> job queue -> analysis job ---------------------------+                    |
|       storage (SQLite, blobs) | airframe store | changes | alerts     |                    |
+-----------------------------------------------------------------------|--------------------+
                                                                        | run_analysis()
+-----------------------------------------------------------------------v--------------------+
| engine (flightmd_core)                                              library / CLI callers  |
|                                                                                            |
|  intake:  open_log -> detect_format -> [parse cache] -> parser in a child process          |
|                                                |                                           |
|  parsers:      topics (tables, us clock), params, metadata + parse_warnings                |
|                                                |                                           |
|  intake:  armed windows, GPS track, path figures;  context: weather, place (optional)      |
|                                                |                                           |
|  analysers:   flight_phases, vehicle -> 9 checks (thread pool) -> AnalyserResult each      |
|                                                |                data: param tables         |
|  report:  score -> explanations -> [AI summary, optional] -> ReportBuilder -> FlightMDReport|
|           exports: JSON, PDF, GPX, KML                                                     |
+--------------------------------------------------------------------------------------------+
```

## 3. Data flow of one analysis

1. The file arrives by upload (`api`), command-line argument or function call
   (`intake`). Its size is checked and its SHA-256 computed.
2. `intake` unpacks a gzip or single-file zip under a byte and ratio cap, and
   identifies the format from the first 4096 bytes.
3. If the parse cache holds this SHA-256 the parse is reused; otherwise the
   parser for the format runs in a child process under a time limit.
4. `parsers` return topics, parameters and metadata. A log with no telemetry
   is refused.
5. `intake` derives armed windows and the GPS track; online, `report` adds
   weather and a place name.
6. `analysers` run the checks that have their inputs, in a thread pool; the
   others return a skip with the reason; a check that raises becomes a skip
   with the error.
7. `report` computes the overall score from the assessed weighted checks,
   explains each finding from templates, optionally has the summary rewritten
   by the AI, and assembles the report: findings sorted, one change sheet,
   numbers made JSON-safe.
8. `api` stores the report and serves it and its exports; `web` shows it.

## 4. Allocation of system requirements

| Item | System requirements |
|---|---|
| `intake` | SYS-001, 002, 003, 006, 007 (armed windows in the report), 017, 020, 025, 027 |
| `parsers` | SYS-001, 004, 005, 025 |
| `analysers` | SYS-007, 008, 009, 010, 011, 012, 013, 014, 016 (proposed), 018 |
| `report` | SYS-002 (no telemetry), 005, 009, 010, 011, 012, 013, 015, 016 (proposed), 019, 020, 021 (proposed), 022, 023, 024, 025, 026 (proposed), 027 |
| `api` | SYS-003, 022, 023, 024, 028, 029, 030, 031, 032, 033, 034, 035 |
| `web` | SYS-022, 026 (proposed), 030, 031, 036, 037 |
| `data` | SYS-014, 039 |
| `tools` | SYS-019, 038, 039 |
| `deployment` | SYS-035 |
| `procedure` | SYS-038 |

The requirement-by-requirement trace is `docs/lifecycle/08-traceability/matrix.md`.

## 5. Interfaces

All seven are written, as built (issue 1).

| Interface | Between | ICD |
|---|---|---|
| Log files | Recorder (autopilot, ground station, app) to `intake` and `parsers` | `icd/icd-log-formats.md` |
| Library and command line | Callers to the engine; environment variables | `icd/icd-cli-library.md` |
| Report and exports | Engine to every consumer: report JSON, PDF, GPX, KML | `icd/icd-report-and-exports.md` |
| HTTP API and alert webhook | `web` and other clients to `api`; `api` to a webhook receiver | `icd/icd-http-api.md` |
| Storage | `api` to disk, optional S3-compatible store and Redis | `icd/icd-storage.md` |
| Web application | Person to `web`; browser storage; parameter files for ground stations; links to and from the planning tool | `icd/icd-web-ui.md` |
| Outside services | Engine to weather, geocoding, AI provider; DJI key service (in `icd-log-formats.md`) | `icd/icd-external-services.md` |

## 6. Properties the architecture relies on

- **One internal form.** Checks read PX4-named topics whatever the source
  format (design standard DS-02). A mapping error in a parser is therefore
  the main way a format-specific wrong result can arise (hazard assessment
  FC-2.1), and the corpus has real logs only for the formats listed in
  `07-verification/README.md`.
- **Isolation of the parse.** Third-party and hand-written decoders run on
  untrusted bytes in a child process that can be stopped. The checks run in
  the calling process.
- **Checks are independent.** Each returns its own result; none reads
  another's. The score is the only place they meet.
- **The AI is outside the rule path.** It is called after scoring and
  explanation, receives text, and its output replaces one string.
- **No path to the vehicle.** No item opens a link to an autopilot or a
  ground station.
