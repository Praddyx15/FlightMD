# High-level design

FMD-HLD, issue 1, 2026-11-20. As built at commit `50a1eba`. The items and
their allocation are in `docs/lifecycle/03-system/system-architecture.md`;
this document says how the software is put together across items. Detail per
item is in `lld-<item>.md`.

## 1. Packages and dependencies between them

```
frontend/  (Next.js)  --HTTP-->  api/  (FastAPI)  --import-->  flightmd_core/  (engine)
                                                                   |
                                             pyulog, pymavlink, numpy, scipy, pandas, pydantic
```

`flightmd_core` imports nothing from `api`. `api` imports the engine's
`run_analysis`, the report models, the exporters and the cache. The web
application knows the service only through `lib/api.ts`, `lib/serverApi.ts`
and the types in `lib/types.ts`.

Inside the engine the dependency direction is: `orchestrator` to
`services` (intake, parsers, report services) and `analysers`; `analysers` to
`models`; `services` to `models`. `score_calculator` reads the weights from
`analysers.registry`. No parser imports a check and no check imports a parser.

## 2. The data that crosses items

| Data | Form | Made by | Used by |
|---|---|---|---|
| Topics | `dict[str, pandas.DataFrame]`; every table has `timestamp` in microseconds, log-relative; topic and column names follow PX4 (`vehicle_gps_position`, `vehicle_status`, `estimator_status`, ...) | Parsers | Orchestrator, checks |
| Parameters | `dict[str, float]` with the autopilot's own names | Parsers | Checks, `vehicle_from_params` |
| `FlightMetadata` | pydantic model: duration, firmware, vehicle, start time, path, armed windows, parse warnings, log hash, source format | Parsers, then the orchestrator adds path, windows, context | Checks (firmware, format), report |
| `AnalyserResult` | pydantic model: findings, module score, skipped and assessed flags, key metrics | Each check | Score, report, trends |
| `Finding` | pydantic model: category, severity, kind, evidence text, time window, confidence, parameter changes | Checks | Explanations, report, web |
| `FlightMDReport` | pydantic model, schema version 1.7 | `ReportBuilder` | API store, exports, web, other software |

The arming state uses PX4's numbering in every format (`arming_state == 2`
is armed); the parsers map their own flags onto it. The report schema is
published in `docs/schema/` and `tests/test_schema.py` holds the model to it.

## 3. Control flow

`run_analysis` (`flightmd_core/orchestrator.py`) is the one entry point for
the API, the command line and library callers:

1. size limit, SHA-256, parse cache lookup;
2. on a miss: unpack, detect, parse in a spawned child process with a time
   limit, progress over a queue; cache the parse;
3. refuse a log with no telemetry topics;
4. armed windows, GPS track and path figures; weather and place when online;
5. load the checks (built-in, then plugins), split into applicable and
   skipped, run the applicable ones in the default thread pool, collect the
   results in list order;
6. overall score; explanations from templates; optional AI rewrite of the
   summary; report assembly.

Progress is reported as a percentage, a message and a time estimate through a
callback that may be sync or async and may fail without stopping the
analysis.

In the service an upload becomes a job (in-process queue, or Redis and
worker processes when configured); the job calls `run_analysis` and stores
the report; the browser polls for status and then fetches the report.

## 4. Design decisions that span items

| Decision | Why | Consequence |
|---|---|---|
| One internal form with PX4 names | Nine checks, six formats: checks are written once | A parser mapping error is invisible to the checks; it is the main systematic risk (FMEA PA-01) |
| Parse in a child process | A thread cannot be stopped; decoders run on untrusted bytes | Parsed data is pickled back over a queue; spawn cost per log |
| Checks declare their inputs and return a skip | A missing topic must not look like a pass | Each check has to tell "nothing to check" from "nothing found" itself (FMEA AN-02) |
| Weights on the check classes | A plugin brings its own | The score's denominator depends on what is installed (FMEA AN-07) |
| Explanations from templates keyed on `kind` | Repeatable text; no model in the rule path | A new `kind` needs a template or gets the technical summary |
| AI after everything else, on text only | It cannot reach a finding | Its text is not marked as AI-written in the report (PR-005) |
| Numbers cleaned once at report assembly | JSON has no NaN | A NaN that decided something earlier is gone from view by then (FMEA AN-04) |
| Parse cache as gzip pickle keyed by SHA-256 | Re-upload, PDF, Q&A and trends reuse a parse | Needs a private directory and a manual version bump (FMEA IN-04, IN-05) |
| SQLite and files under one data directory | One process, small host | More than one API process needs Redis; a host without a persistent disk loses history |

## 5. Concurrency

- The parse runs in one child process per analysis.
- The checks run concurrently in threads on the same topic tables. They are
  meant to read only; this has not been verified per check (FMEA IN-08).
- The service limits analyses running at once (`MAX_CONCURRENT_ANALYSES`).

## 6. Determinism

Given the same log, engine version, installed plugins and environment
variables, the findings, their order, the scores and the change sheet are the
same. What differs between runs: the report identifier, each finding's `id`,
the time of generation and the processing times; online, the weather, the
place name and the AI summary. The argument is by inspection (results are
gathered in list order, the final sort is stable); the corpus test checks
kinds, severities, assessed modules and metrics within tolerances, not full
equality (PR-016).

## 7. Gaps against the design standard

Recorded as problem reports: DS-08 (silent drops, PR-010), DS-11 (zero-filled
path values, PR-007), DS-15 (errors that escape as the wrong type, PR-012),
DS-12 holds but the AI text is unmarked (PR-005).
