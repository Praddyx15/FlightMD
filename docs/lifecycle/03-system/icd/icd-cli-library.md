# ICD: command line and Python library

FMD-ICD-CLI, issue 1, 2026-11-20.

The two ways into the analysis engine without the HTTP API: the `flightmd` command and the coroutine
`run_analysis`. Facts are from `flightmd_core/__main__.py`, `flightmd_core/orchestrator.py`,
`flightmd_core/cache.py` and `flightmd_core/__init__.py` as built. Governing requirements: HLR-INT-007,
008, 009, 012 to 014, 017, 018, 021 to 023, 025 and 027.

## 1 Command line

Entry points: console script `flightmd` (`flightmd_core.__main__:main`) and `python -m flightmd_core`.
Both call `main(argv=None) -> int`; the return value is the process exit code.

### 1.1 `flightmd analyse`

```
flightmd [analyse] LOG [--json FILE] [--pdf FILE] [--gpx FILE] [--kml FILE] [--offline | --online]
```

The word `analyse` may be left out when the first argument is not `analyse`, `compare` or an option.

| Argument | Direction | Meaning |
|---|---|---|
| `LOG` | in | Path of one log, or a gzip or zip holding one log. The format is taken from the content. |
| `--json FILE` | out | The full report, UTF-8 JSON, 2-space indent |
| `--gpx FILE` | out | Flight path as GPX |
| `--kml FILE` | out | Flight path as KML |
| `--pdf FILE` | out | PDF report; needs the optional PDF dependency |
| `--offline` | in | Sets `FLIGHTMD_OFFLINE=1` |
| `--online` | in | Sets `FLIGHTMD_OFFLINE=0` |

With neither flag `FLIGHTMD_OFFLINE` is set to `1` unless it is already set in the environment. The two
flags cannot be given together. No AI enhancer is ever passed.

Outputs are written in the order JSON, GPX, KML, PDF, each to `FILE.part` and then renamed onto `FILE`.

Standard output on success:

```
<file name>: <score>/100 (<grade>, <label>)
  note: <parse warning>            (one line each)
  [<SEVERITY>] <finding title>     (one line each, report order)
```

The score is printed without decimals. A report in which nothing was assessed prints `0/100 (-, Not
assessed)`. Standard error carries a progress line (`[ 42%] message  ~N s left`, rewritten in place) only
when it is a terminal, and the error messages below.

| Exit code | When | Standard error |
|---|---|---|
| 0 | Report made, every export asked for written | - |
| 1 | `run_analysis` raised `ValueError` | `error: <reason>` |
| 2 | `LOG` is not a file | `error: no such file: <path>` |
| 2 | Bad arguments (from `argparse`) | usage text |
| 3 | PDF rendering raised `RuntimeError`; JSON, GPX and KML already written; no summary printed | `error: no PDF: <reason>` |

Any other exception (for example a write error on an export) is not caught and ends with a traceback.

### 1.2 `flightmd compare`

```
flightmd compare BEFORE AFTER
```

`BEFORE` and `AFTER` are report JSON files as written by `--json`. Standard output:

```
<before file_name> -> <after file_name>
  score <B> -> <A> (<+D>)
  <module>: <b> -> <a> (<+d>)      (changed modules; "-" for a side that is missing, skipped or not assessed)
  resolved: <title>                (finding only in BEFORE)
  new:      <title>                (finding only in AFTER)
```

Findings are matched on (`kind`, or `title` when there is no kind; `severity`). Modules with a delta of 0
are not printed.

| Exit code | When | Standard error |
|---|---|---|
| 0 | Comparison printed | - |
| 2 | A file cannot be read or is not JSON | `error: can't read <path>: <reason>` |

As built: `overall_score` missing or `null` in either file ends with an uncaught `TypeError`; a "Not
assessed" report has `overall_score` 0.0 and is shown as score 0.

`compare_reports(a: dict, b: dict) -> dict` gives the same comparison as data: `before`, `after`,
`score_before`, `score_after`, `score_delta`, `modules` (`{name: {before, after, delta}}`),
`findings_resolved`, `findings_new`.

## 2 Python entry point

```python
from flightmd_core import run_analysis
report = await run_analysis(ulog_path, file_name, file_size,
                            progress_callback=None, ai_enhancer=None)
```

| Argument | Type | Meaning |
|---|---|---|
| `ulog_path` | `str` | Path of the file to analyse (any supported format, or a gzip or zip of one). Read only. |
| `file_name` | `str` | Name put in the report. Not checked, not used to find the file. |
| `file_size` | `int` | Size in bytes put in the report. Not checked; the size limit uses the size on disk. |
| `progress_callback` | callable or `None` | See 2.1 |
| `ai_enhancer` | `AIEnhancer` or `None` | Used only when configured and not offline, and only to rewrite the executive summary |

Returns a `FlightMDReport` (its format version is in `report.schema_version`). Must be awaited on a
running event loop; it uses the loop's default thread pool and, unless the parse timeout is 0 or less, one
child process per call.

Set by this entry point in `report.metadata`: `log_sha256` (SHA-256 of `ulog_path` as given, before any
decompression), `source_format` (`px4_ulog`, `ardupilot_bin`, `ardupilot_log`, `mavlink_tlog`,
`betaflight_bbl` or `dji_txt`), `armed_windows`, `gps_path` and its companions, `weather`,
`location_name`, and additions to `parse_warnings`.

### 2.1 Progress callback

`progress_callback(pct: int, message: str, eta_s: float | None)`, a plain function or a coroutine
function (an awaitable result is awaited).

- `pct` never goes down between calls; the same value can repeat. First call 5, last call 100.
- Steps: 5 reading; 5 to 60 parsing (60 at once when the parse comes from the cache); 62 weather (online
  only); 65 analysers; 80 score; 88 explanations; 92 AI summary (only when used); 96 assembling; 100.
- `eta_s` is an estimate in seconds rounded to 0.1, never negative; the last call gives 0.0.
- An exception from the callback is logged and ignored.
- Parse progress is delivered from another thread through the event loop, so a call can arrive after a
  later step; such late calls with a lower `pct` are dropped. When `run_analysis` raises during the
  parse, a parse-progress call already scheduled can still arrive afterwards.

### 2.2 Errors

`ValueError` (message for the user) for: file over the size limit; unrecognised or unsupported format
(the detector's `UnsupportedFormatError` text); archive refused (damaged, not exactly one file, unsafe
entry path, password protected, nested, too large, expands too much); parser failure ("Failed to parse
<format> file: ..."); parse over the time limit; parser process stopped; no analysable telemetry.

As built, other exception types can leave `run_analysis`: `OSError` when `ulog_path` cannot be read,
`NotImplementedError` for a zip compression method the runtime cannot read, errors from a damaged cache
entry other than those the cache handles, and any error raised after the parse.

## 3 Environment variables

Read at each call, not at import. Numeric values that are not numbers fall back to the default.

| Variable | Default | Effect |
|---|---|---|
| `FLIGHTMD_OFFLINE` | unset (online) for the library; `1` for the command line | `1`, `true`, `yes`, `on`: no weather, place-name or AI call, and no DJI key exchange in the DJI parser |
| `FLIGHTMD_MAX_LOG_MB` | 512 | Largest file accepted and largest unpacked size, in MB of 1 000 000 bytes |
| `FLIGHTMD_PARSE_TIMEOUT_S` | 600 | Seconds before the parser process is stopped; 0 or less parses in-process with no limit |
| `FLIGHTMD_DATA_DIR` | unset | Base directory; the parse cache is `<dir>/cache` (`data/cache` when unset) |
| `FLIGHTMD_CACHE` | unset | `0`, `false`, `no`, `off` turn the cache off; any other non-empty value turns it on; unset: on only when `FLIGHTMD_DATA_DIR` is set |
| `FLIGHTMD_CACHE_TTL_S` | 3600 | Seconds since last write or read after which an entry is dropped |
| `FLIGHTMD_CACHE_MAX_MB` | 1024 | Total cache size in MB of 1 000 000 bytes; oldest entries go first |
| `DJI_API_KEY` | unset | Read by the DJI parser (parsers item) for version 13 and later records |

The cache directory holds pickle files and must be writable by this software only.

## 4 Versioning

- The report format is versioned by `schema_version` in the report.
- The package states `flightmd_core.__version__ = "1.0.0"`; the distribution metadata in `pyproject.toml`
  says 1.1.0. Neither appears in the report or in any command-line output; the command has no version
  option.
- Cache entries carry `CACHE_VERSION` (2) in their file name; entries of another version are deleted on
  prune.
- Command-line compatibility kept: the form without the `analyse` word.
