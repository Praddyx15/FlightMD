# Design standard

FMD-DS, issue 1, 2026-11-20. Rules the design follows, taken from how the code
is built today. Reviews cite the rule ids. A rule the code breaks is a problem
report, not an exception here.

| Rule | Text | Checked by |
|---|---|---|
| DS-01 | The engine (`flightmd_core`) imports nothing from `api/` or `frontend/`. The API imports the engine; the web application talks to the API over HTTP only | Review; `pyproject.toml` packages only `flightmd_core*` |
| DS-02 | Every parser returns the same three things: topics (name to table, `timestamp` in microseconds on a log-relative clock, PX4 topic and column names and units), parameters (name to number) and `FlightMetadata`. A check never looks at the source format to read a value; format differences end in the parser | Review; parser tests |
| DS-03 | A unit conversion happens once, in the parser, and is stated in an LLR with its factor. The web application converts for display only (DS-11) | Review; LLR-PRS, LLR-WEB |
| DS-04 | A check declares what it needs (`required_topics`, `required_any`, `required_columns`, `formats`) and returns a skip, not a clean result, when it has nothing to check | Tests per check; review |
| DS-05 | A threshold is a named module constant with its unit in the name or a comment, never a number inside an expression | Review |
| DS-06 | Findings carry a stable `kind`. Explanations, grouping, trends and tune-fly-verify key on `kind` and parameter names, never on titles | Tests; review |
| DS-07 | The result of an analysis depends only on the log, the parameters of the run (environment variables) and the code version. No random numbers, no wall clock in a rule, no result that depends on thread timing or on set order | Corpus test; review |
| DS-08 | Anything a parser or the pipeline skips, guesses or falls back on is added to `parse_warnings` in words a user understands | Review; parser tests |
| DS-09 | Outside input (uploads, archives, report files, webhook addresses, form fields) is checked once where it enters, with a size bound. Work on an upload is bounded in bytes and in time | Tests; review |
| DS-10 | The report model is the data contract. Fields are added as optional, never renamed or removed; a change bumps `schema_version`, the published schema and the changelog in the same pull request | `tests/test_schema.py` |
| DS-11 | Report data is never changed for presentation: numbers are sanitised once in the report builder; the web application and exports format copies | Review |
| DS-12 | The optional AI gets report text and returns text. No code path writes AI output into a finding, a score or a parameter value | Tests; review |
| DS-13 | Network calls from the engine go through one function each (weather, geocoding, AI, DJI key), each with a timeout, each off in offline mode, each failing to a stated "not available" value | Tests; review |
| DS-14 | Files that matter are written beside the target and renamed over it; a reader never sees half a file | Review |
| DS-15 | A failure in one check, one plugin, one alert or one export does not take down the analysis or the service; it is reported where the user or the operator can see it | Tests; review |

## Design descriptions

- `06-design/hld.md`: the items, the data flow between them and the design
  decisions that span items.
- `06-design/lld-<item>.md`: one per software item, as built: files, structure
  and data flow with the LLR ids, data and constants, error handling, limits,
  known gaps.
- Interfaces are in `03-system/icd/`. The report schema's formal definition is
  `docs/schema/flightmd-report-<version>.json`.

A design change is made in the code and its LLD in the same pull request, with
the LLR it changes.
