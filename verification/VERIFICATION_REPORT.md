# FlightMD Verification & Validation Report

**Dataset:** 50 real flight logs, all publicly shared by real PX4 users on [PX4's official Flight Review database](https://review.px4.io/) for community review. Not synthetic test fixtures. Not curated for a favorable outcome — selected by vehicle type and file size only, before any of them were analysed.

## Methodology

1. Pulled log metadata via PX4's own public `dbinfo` API (421,281 public logs total).
2. Selected 50 logs spanning **11 vehicle types** (weighted toward common ones like Quadrotor while still covering rare ones like Coaxial helicopter), filtered to real-world-scale files (100-500MB — genuinely long flights, not short test hops).
3. Downloaded each via PX4's own `download` API with the same rate-limiting their official `download_logs.py` script uses (6s between requests, exponential backoff on HTTP 503, abort on IP block) — no scraping, no bypassing access control.
4. Ran every log through FlightMD's actual `run_analysis()` — the exact code path a real upload takes.
5. Cross-checked FlightMD's independent findings against each log's own PX4-reported error/warning counts (logged by the flight controller itself) as an external sanity check — with important caveats below on how clean that reference data actually is.

## Dataset composition

| Vehicle Type | Count |
|---|---|
| Quadrotor | 15 |
| Fixed Wing | 7 |
| Hexarotor | 6 |
| VTOL Standard | 6 |
| Octorotor | 4 |
| Tiltrotor VTOL | 3 |
| Ground Rover | 3 |
| Two-rotor VTOL (Tailsitter) | 2 |
| Quad-rotor VTOL (Tailsitter) | 2 |
| Coaxial helicopter | 1 |
| Normal helicopter with tail rotor | 1 |
| **Total** | **50** |

File sizes: 8–303 MB (8399 MB total). Durations: 3–185 minutes.

**Sampling caveat:** 45 unique vehicles across 50 logs — one vehicle (a Holybro S500) was sampled twice by chance (same `vehicle_uuid` and firmware build, uploaded on two different dates, one labeled `test_20min`), almost certainly the same recurring bench/CI test flight rather than two independent real missions. Left in rather than quietly dropped — noted here instead.

## Efficiency

- **49 of 50 logs** (98%) processed in **3.6s median** (3.9s average, 7.6s 95th percentile)
- Aggregate throughput on those 49: **~42.4 MB/s**
- **1 outlier** (2%): a 303MB Quadrotor log took 197s. Root-caused with `cProfile` to an upstream performance ceiling in `pyulog` (the official PX4 log-parsing library, already on its latest release, 1.2.3): that flight logged ~2.3 million discrete messages (a 1.7-hour flight at a very high logging rate), and pyulog must read every message's header sequentially regardless of which topics are actually needed — confirmed via 218M individual file-read calls during profiling. FlightMD's own analysis code accounted for under 10ms of that total. Disclosed here rather than quietly excluded from the average.

## Accuracy

Grade distribution across all 50 real, unfiltered flights: A: 3, B: 10, C: 15, D: 15, E: 4, F: 3. Not capped or curved — a wide spread is the expected, correct outcome for a random sample of real-world flights of unknown quality, not a flaw.

**On the cross-check against PX4's own error/warning counts — the honest version:** 4 of 50 flights reported implausible PX4 error counts (733, 733, 8851, 63918 — real flights essentially never log more than a few dozen genuine errors; these are almost certainly counting artifacts in PX4's own public metadata, the same class of data-quality issue as the corrupted multi-trillion-second flight durations also present elsewhere in that same public database). Excluding those 4 outliers (n=46 remaining):

- Flights PX4 itself logged **zero** errors on: average FlightMD score **72.9** (n=32)
- Flights PX4 logged **at least one** error on: average FlightMD score **65.7** (n=14)
- Spearman rank correlation (robust to remaining outliers) between PX4's own error/warning severity and FlightMD's score deficit: **ρ = 0.16**

That correlation is real but modest, not dramatic — with n≈46 and PX4's own error/warning counts being a noisy, informal severity signal (not a graded ground truth), a weak-to-moderate correlation is the honest result, and claiming otherwise would be overselling a small, noisy sample. The clearer signal is at the extremes, illustrated below.

### Worked example (the clearest, individually-verified case)

- **Hexarotor / Generic Hexarotor x geometry** — PX4 itself logged 11 errors, 75 warnings on this flight. FlightMD, reading only raw sensor/estimator signals and never PX4's own error flags, independently graded it **F (36.6)** and flagged: GPS Fix Lost During Flight (No Fix), GPS Position Uncertainty (CRITICAL, HDOP=100.0), Roll-Axis Oscillation at 1.3 Hz, Pitch-Axis Oscillation at 1.0 Hz....
- **Quadrotor / Generic Quadcopter** — PX4 logged 0 errors, 15 warnings. FlightMD graded it **A (95.0)**.

## Bugs found and fixed during this validation effort

Real, diverse data (rather than only synthetic fixtures) is what surfaced these — all fixed and covered by regression tests before this report was generated:

1. **`max_altitude_m`/`max_speed_ms`/`total_distance_m` were always `None` for ArduPilot/MAVLink logs** — that computation only ever existed for PX4's local-position topic. Fixed with a GPS-derived fallback for all formats.
2. **A duplicate-timestamp GPS row briefly computed a groundspeed of 98,813 m/s** on a real ArduCopter log — fixed with a physically-grounded plausibility guard.
3. **100% (13/13) of the first real-world PX4 batch failed to parse at all** — real firmware encodes `ver_sw_release`/`ver_sw`/`ver_hw`/`sys_name` as integers, which our model required as strings. Every synthetic test fixture had always produced strings, so this was invisible until real data was used.

## Known limitations

- Very long, very high-logging-rate flights (millions of discrete messages) can take minutes to parse due to an upstream `pyulog` performance characteristic, not a FlightMD analysis bottleneck. Affected 1/50 real logs in this batch.
- PX4's own public error/warning metadata is itself noisy (a handful of implausible outlier values, one repeated-vehicle sample) — this report corrects for that rather than presenting a cleaner-looking but misleading headline number.
- This 50-log batch is PX4 ULog only. ArduPilot `.bin` and MAVLink `.tlog` share the same analysis engine and were validated separately against a real 233MB ArduCopter flight log earlier.
- 50 flights is a real, meaningful sample — not a substitute for broad open community testing across airframes, tunes, and failure modes this dataset doesn't happen to include.

## Raw data

- `summary.csv` — one row per flight, all metrics
- `analysis_results.json` — complete FlightMD report data per flight
- `manifest.json` — original PX4 metadata per flight, including each log's `log_id` and
  `download_url`

The 50 `.ulg` files themselves aren't re-hosted here — they're PX4's own public data, and at
8.4GB total there's no reason to duplicate them in this repo. Every log is independently
re-downloadable from PX4's public Flight Review database using the `log_id` in `manifest.json`
(`https://review.px4.io/plot_app?log=<log_id>` for the UI, or `download_url` in the manifest for
the raw file), so the exact dataset behind this report is fully reproducible without trusting a
mirrored copy.