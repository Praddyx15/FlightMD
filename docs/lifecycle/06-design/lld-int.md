# Intake and pipeline low-level design

FMD-LLD-INT, issue 1, 2026-11-20.

As built. Requirements: `05-requirements/hlr-int.sdoc`, `05-requirements/llr-int.sdoc`. Interface:
`03-system/icd/icd-cli-library.md`.

## 1 Purpose and code

The item takes a file, decides what it is, bounds the work it can cause, gets it parsed, and drives the
rest of the analysis to a report. It also holds the command line.

| File | Contents |
|---|---|
| `flightmd_core/services/format_detector.py` | Format from the first 4096 bytes; `PARSERS` table; `UnsupportedFormatError` |
| `flightmd_core/services/compressed.py` | `open_log`: gzip and zip unpacking with size and ratio caps |
| `flightmd_core/services/columns.py` | `ColumnBuffer`: float64 row store used by the dataflash and telemetry parsers |
| `flightmd_core/cache.py` | Parse cache: one gzip pickle per log, keyed by SHA-256 |
| `flightmd_core/orchestrator.py` | `run_analysis`: the pipeline; parse in a child process; armed windows; path |
| `flightmd_core/__main__.py` | `flightmd analyse` and `flightmd compare` |
| `flightmd_core/__init__.py` | Exported names, `__version__` |

## 2 Structure and data flow

```
run_analysis(ulog_path, file_name, file_size, progress_callback, ai_enhancer)
 |  size on disk > FLIGHTMD_MAX_LOG_MB ? ValueError               LLR-INT-041
 |  file_sha256(ulog_path)                                        LLR-INT-034
 |  cache.enabled() ? cache.get(sha)                              LLR-INT-026..029, 044
 |    hit  -> (topics, params, metadata), progress 60
 |    miss -> _open_and_parse                                     LLR-INT-039, 040
 |              open_log (gzip / zip / plain)                     LLR-INT-013..022
 |              detect_format (first 4096 bytes)                  LLR-INT-001..012
 |              _parse_with_limit -> spawn _child -> _parse       LLR-INT-035..038
 |              cleanup(); metadata.source_format = format
 |            metadata.log_sha256 = sha; cache.put(...)           LLR-INT-030, 031, 044
 |  only status topics ? ValueError                               LLR-INT-046
 |  _armed_windows -> metadata.armed_windows (+ parse warning)    LLR-INT-047, 048
 |  _gps_track -> _fill_path (path, HDOP, wind, alt, dist, speed) LLR-INT-049..053
 |  weather / place name, or the reason there is none             LLR-INT-033, 054
 |  load_analysers(metadata); safe_analyse in threads; skip rest  LLR-INT-055
 |  ScoreCalculator -> ExplanationEngine (-> fallback on error)   LLR-INT-056, 057
 |  ai_enhancer.polish_summary (summary text only)                LLR-INT-058
 |  ReportBuilder().build(...) -> FlightMDReport                  LLR-INT-045
 v  progress 100 "Done."                                          LLR-INT-042, 043

flightmd (main)                                                   LLR-INT-069
 |- analyse: run_analysis under asyncio.run; exports; summary     LLR-INT-059..064
 `- compare: two report JSON files -> compare_reports -> text     LLR-INT-065..068
```

Threads and processes: `run_analysis` is a coroutine. Hashing, the cache read and write, `open_log`,
`detect_format`, the parse wait, weather, place name and each analyser run in the event loop's default
thread pool. The parser itself runs in a child process started with the `spawn` method and sends
`("progress", frac)`, `("done", result)` or `("error", exc)` over one `multiprocessing` queue. Parse
progress is scheduled back onto the loop with `run_coroutine_threadsafe` and is not awaited.

Order of results: `asyncio.gather` returns in the order of the analyser list (built-ins in registry order,
then plugins), not in order of completion; skipped analysers follow. Findings are the concatenation.

## 3 Data

`(topics, params, metadata)` is what a parser returns: `dict[str, DataFrame]` with a `timestamp` column in
log-relative microseconds, `dict[str, float]`, and `FlightMetadata`. A cache entry is
`{"topics", "params", "metadata": metadata.model_dump()}`.

| Name | Value | Unit | Where used |
|---|---|---|---|
| `HEADER_BYTES` | 4096 | bytes | `detect_format` |
| `ULOG_MAGIC` | `ULog\x01\x12\x35` | 7 bytes | detection |
| `DATAFLASH_HEAD`, `DATAFLASH_FMT` | `A3 95`, `0x80` | bytes | `_check_dataflash` |
| `MAVLINK_V1_STX`, `MAVLINK_V2_STX` | `0xFE`, `0xFD` | byte | `_tlog_frame_len` |
| `TLOG_FRAMES_NEEDED` | 3 | records | `_check_tlog` |
| `GZIP_MAGIC`, `ZIP_MAGICS` | `1f 8b`; `PK\x03\x04`, `PK\x05\x06` | bytes | `open_log` |
| `MAX_RATIO` | 200 | unpacked / packed | `_zip_source`, `_copy_capped` |
| `RATIO_FLOOR_BYTES` | 1 048 576 | bytes | ratio not checked below this |
| `CHUNK` | 65 536 | bytes | `_copy_capped` |
| `MIN_ROWS` | 256 | rows | `ColumnBuffer` first block |
| `CACHE_VERSION` | 2 | - | entry suffix `.v2.pkl.gz` |
| `FLIGHTMD_CACHE_TTL_S` | 3600 | s | `cache.get`, `prune`; stale `.tmp-` files also 3600 s |
| `FLIGHTMD_CACHE_MAX_MB` | 1024 | MB of 1e6 bytes | `prune` |
| `FLIGHTMD_MAX_LOG_MB` | 512 | MB of 1e6 bytes | `run_analysis`, then `open_log` as bytes |
| `FLIGHTMD_PARSE_TIMEOUT_S` | 600 | s, monotonic clock | `_parse_with_limit`; 0 or less = no limit |
| `PARSE_START`, `PARSE_END` | 5, 60 | % | progress during the parse |
| `PARSE_MB_PER_S` | ULog 12, bin 5, text 2, tlog 3; else 4 | MB/s | first time estimate only |
| `ANALYSIS_BASE_S`, `ANALYSIS_S_PER_MB` | 2.0, 0.04 | s, s/MB | time estimate after the parse |
| `MIN_GPS_DT_S` | 0.05 | s | shortest segment counted |
| `MAX_PLAUSIBLE_SPEED_MS` | 75.0 | m/s | fastest segment counted |
| `PATH_POINTS` | 500 | points | divisor for the sampling step |
| earth radius | 6 371 000 | m | equirectangular distance in `_fill_path` |
| armed state | `arming_state == 2` | - | `_armed_windows` |

Units set by this item in the metadata: `armed_windows` and `gps_path_t_s` in log-relative seconds
(3 decimals); `gps_path` as `[lat deg, lon deg, alt m]`; `max_altitude_m` (0.1 m), `total_distance_m`
(0.1 m), `max_speed_ms` (0.01 m/s); wind in m/s. Receiver `lat`/`lon` arrive as degrees times 1e7 and
altitude in millimetres; estimator positions arrive in degrees and metres.

## 4 Error handling

| Where | Raised | Caller sees |
|---|---|---|
| Size over limit, no telemetry | `ValueError` | `ValueError` |
| `open_log` refusals (damaged, count, unsafe path, password, nested, size, ratio) | `ValueError` | `ValueError` |
| `detect_format` | `UnsupportedFormatError` | `ValueError` with the same text |
| Parser raises `ValueError` | passed on | `ValueError` |
| Parser raises anything else | wrapped | `ValueError` "Failed to parse <format> file: ..." |
| Parse over time, child dead | `ValueError` | `ValueError` |
| Cache read or write `OSError` | logged | none (miss, or entry not written) |
| Cache entry unreadable (five exception types) | logged, entry deleted | none (miss) |
| Progress callback raises | logged | none |
| Explanation engine raises | logged | none; fixed fallback texts |

Swallowed on purpose: a cache failure must not stop an analysis; a callback belongs to the caller; a
failed delete (`_drop`) is retried by the next prune.

Not converted (leave `run_analysis` with their own type): `NotImplementedError` from a zip compression
method the runtime cannot read; a cache-entry error outside the five handled types; anything raised by
`_armed_windows`, `_gps_track`, `_fill_path`, the weather and place-name calls, `load_analysers`,
the score calculator, the AI enhancer or the report builder. The command line catches `ValueError` only
(exit 1) and `RuntimeError` from the PDF only (exit 3); anything else is a traceback.

## 5 Resource use and limits

- Disk: an archive is unpacked once into a `flightmd-` temporary directory, at most
  `min(limit, max(200 x packed size, 1 MiB))` bytes, removed on every path out of `_open_and_parse`.
- Memory: the parse result crosses the queue pickled, so it exists once in the child and once in the
  parent while it is received. `ColumnBuffer` holds one float64 block and doubles it when full; `frame`
  copies the used rows.
- Time: the parse is bounded by `FLIGHTMD_PARSE_TIMEOUT_S`; the child is terminated and joined for at
  most 5 s. Nothing bounds the analysers, the explanations or the report assembly.
- Concurrency: analysers share the thread pool and the same `topics` frames. This item does not limit how
  many analyses run at once; that limit is the API's.
- Cache: one file per log; size cap enforced after each write, not before, so the directory can exceed
  the cap by one entry until `prune` runs.

## 6 Known gaps and deviations

Each is recorded as built in the LLR named and reported as a defect. Item 1 was fixed in issue 1 (PR-003);
the others are open.

1. Fixed: a damaged cache entry that raised outside the five handled types was not dropped and failed the
   analysis of that log until it expired. Every read or rebuild error now drops it (LLR-INT-029).
2. The cache time limit runs from the last read, so an entry read at least hourly never expires
   (LLR-INT-028).
3. The path can hold up to 999 points; SYS-017 says 500 (LLR-INT-051).
4. Segments over 75 m/s are left out of distance and maximum speed with no note in the report; the points
   themselves stay on the path (LLR-INT-052).
5. NaN latitude or longitude passes the not-zero filter and becomes 0.0 in the path; a missing altitude
   becomes 0.0 m (LLR-INT-049, LLR-INT-051).
6. `compare` fails with an uncaught `TypeError` on a report without a numeric `overall_score`, and shows a
   "Not assessed" report as score 0 (LLR-INT-067, LLR-INT-068).
7. Not every failure is a `ValueError` (section 4; LLR-INT-022, LLR-INT-039, LLR-INT-045; against SYS-027).
8. A file of 4096 bytes or more named `.txt` can be accepted as a DJI record on its extension when the
   header is undecided (LLR-INT-009, LLR-INT-011).
9. The explanation fallback recommends "a PX4 expert" for every autopilot (LLR-INT-057).
10. `nan` and `inf` are accepted as numeric settings (LLR-INT-032).
11. `__version__` is 1.0.0 and `pyproject.toml` says 1.1.0; the report carries neither (LLR-INT-070).
12. The corpus check allows a score change of up to 5 points and does not compare confidence, evidence,
    time windows or parameter recommendations (LLR-INT-072).
13. The wind value for a path point is the nearest estimator row with no limit on the time gap
    (LLR-INT-053).
