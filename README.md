# FlightMD

Flight log analysis for PX4, ArduPilot, Betaflight and DJI, in plain English.

[![CI](https://github.com/Praddyx15/FlightMD/actions/workflows/ci.yml/badge.svg)](https://github.com/Praddyx15/FlightMD/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Drop in a flight log and FlightMD tells you what went wrong in the flight, why, and which parameter
to change. The format is detected from the file contents, not the extension.

Every finding comes from a deterministic rule engine, so the same log always gives the same report
and every severity can be traced to a threshold in the code. An AI layer is optional. When it's
switched on it only rewrites the executive summary and answers questions about the report; it never
adds or changes a finding.

## Formats

| Format | Files | Notes |
|---|---|---|
| PX4 ULog | `.ulg` | |
| ArduPilot dataflash | `.bin`, text `.log` | |
| MAVLink telemetry | `.tlog` | Filtered to the autopilot's system id |
| Betaflight / INAV blackbox | `.bbl`, `.bfl`, `LOG*.TXT` | Pure-Python decoder; a 5 min 2 kHz log takes a minute or two |
| DJI flight record | `DJIFlightRecord_*.txt` | v1–12 offline. v13+ is encrypted: set `DJI_API_KEY` and install the `dji` extra; the key exchange goes to DJI's servers |

Any of them can also come inside a `.gz` or a `.zip` holding one log. DJI `.DAT` files are recognised
but not supported: recent aircraft encrypt them and there's no openly licensed decoder.

## What you get

- A health score (0–100, A–F) weighted across the modules that could actually be assessed. A log
  with no usable telemetry says "Not assessed" instead of pretending to be a perfect flight.
- Findings for oscillation, vibration, EKF, battery, GPS, parameters and motors, each with a
  plain-English explanation, a time window you can jump to on the charts and the map, and a
  confidence level.
- Checks run on the part of the log where the vehicle was armed or in the air, so GPS acquisition
  on the pad or motors spinning down after landing don't show up as faults. Logs without arming
  data fall back to the whole log, and the report says so.
- The autopilot's own health numbers come first: PX4's vibration metrics and clip counters,
  ArduPilot's VIBE, EKF test ratios and board power.
- Parameter checks against the firmware's own metadata (PX4 1.13–1.15, ArduPilot Copter, Plane and
  Rover 4.6–4.7), picked to match the log's firmware.
- A parameter change sheet you can paste into Mission Planner (`NAME,VALUE`) or load into
  QGroundControl (tab-separated with the QGC header).
- Tune, fly, verify: mark the changes you applied, fly again with the same airframe tag, and the
  airframe page shows whether the findings behind those changes went away.
- Exports: PDF (or print the page), JSON, GPX with timestamps, KML with per-point HDOP and wind.
- Opt-in per-airframe history: trends, maintenance log, pre-flight checklist and webhook alerts.
- Side-by-side comparison of two flights.
- Dark "ops" and light "field" themes, and metric, imperial or aviation units.

## Walkthrough

[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) goes through a report from upload to verified fix. The narrated
video and the screenshots are rendered from the running app by [`tools/walkthrough`](tools/walkthrough/README.md).

## Run it

Python 3.11–3.13 and Node 20+.

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

API on :8000, web on :3000, data in a named volume. `docker compose --profile queue up -d` adds Redis
and a worker.

### API

```bash
pip install -r api/requirements.txt
python -m uvicorn api.main:app --reload
```

Run it from the repo root; the app imports its modules as `api.*`. Data lives in
`FLIGHTMD_DATA_DIR` (default `./data`): a SQLite database, uploads, contributed logs and cached
exports. JSON stores from older versions in `api/data/` are imported on first start.

One API process uses an in-process queue. More than one needs Redis (`FLIGHTMD_REDIS_URL`, the
`queue` extra, and `arq api.worker.WorkerSettings` for the workers).

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

`API_URL` is the address the Next server itself uses to reach the API when it renders a report
(in Compose that's `http://api:8000`). It falls back to `NEXT_PUBLIC_API_URL`.

Colours come from `frontend/design/tokens.json`, the suite's shared token file; `app/tokens.css` is
generated from it on `dev` and `build`. UI text lives in `frontend/messages/en.json`.

### Command line

```bash
pip install .                        # or flightmd-core from PyPI once published; add [pdf] for PDF
flightmd analyse flight.ulg --json report.json --pdf report.pdf --gpx track.gpx
flightmd compare before.json after.json
```

Runs offline by default; `--online` looks up weather and place names.

### As a library

```python
from flightmd_core import run_analysis

report = await run_analysis(ulog_path="flight.ulg", file_name="flight.ulg", file_size=1234567)
print(report.overall_score, report.score_label)
for f in report.findings:
    print(f.severity, f.title, f.t_start_s, f.params)
```

Pass `ai_enhancer=AIEnhancer(...)` from `flightmd_core.services.ai_enhancer` to get the polished
summary. `run_analysis` raises `ValueError` for anything it can't analyse (unknown format, too big,
no telemetry, parse timeout).

Extras: `ai` (Groq/Anthropic clients), `pdf` (WeasyPrint; needs Pango from the OS), `s3`, `queue`,
`dji`.

### Tests

```bash
pip install -r api/requirements.txt -r api/requirements-dev.txt
pytest -m "not integration and not corpus"   # unit tests
pytest -m integration                        # the sample logs in tests/sample_logs/
pytest -m corpus                             # 17 real public logs, downloaded once (~170 MB)

cd frontend
npm test            # Vitest
npm run lint
npm run typecheck
npm run test:e2e    # Playwright; needs the API running and `npx playwright install chromium`
```

The corpus has no expected results checked in yet. The first time, run
`pytest -m corpus --update-golden`, read through `tests/corpus/golden/`, and commit what you agree
with. After that the weekly CI job catches regressions.

## Configuration

Everything is optional. [`.env.example`](.env.example) has the full list with comments.

| Variable | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | `groq` | `groq` (free tier) or `anthropic` |
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | | Turns on the AI summary and Q&A |
| `FLIGHTMD_OFFLINE` | `0` (API), `1` (CLI) | No weather, geocoding, AI or DJI key requests |
| `FLIGHTMD_DATA_DIR` | `./data` | Database, uploads, blobs, export and topic caches |
| `FLIGHTMD_MAX_LOG_MB` | `512` | Biggest log the engine will open (after decompressing) |
| `FLIGHTMD_PARSE_TIMEOUT_S` | `600` | Parse in a child process and stop it after this. `0` parses in-process |
| `FLIGHTMD_CACHE`, `FLIGHTMD_CACHE_TTL_S`, `FLIGHTMD_CACHE_MAX_MB` | on with a data dir, `3600`, `1024` | Parsed-topic cache keyed by the log's SHA-256 |
| `FLIGHTMD_REDIS_URL` | | Use Redis and arq workers instead of the in-process queue |
| `FLIGHTMD_S3_BUCKET` (+ `_PREFIX`, `_ENDPOINT_URL`, `_REGION`) | | Contributed logs in S3-compatible storage |
| `DJI_API_KEY` | | Decrypt DJI v13+ flight records |
| `MAX_FILE_SIZE_MB` | `50` | Upload limit on the API |
| `MAX_CONCURRENT_ANALYSES` | `2` | Analyses running at once; further uploads get a 503 |
| `RATE_LIMIT_PER_HOUR`, `ASK_RATE_LIMIT_PER_HOUR`, `PDF_RATE_LIMIT_PER_HOUR` | `10`, `30`, `30` | Per client IP |
| `TRUSTED_PROXIES` | empty | Proxies whose `X-Forwarded-For` is believed |
| `ALLOW_HTTP_WEBHOOKS` | `false` | Alert webhooks are https-only otherwise |
| `METRICS_TOKEN` | | Bearer token for `/metrics` (Prometheus) |
| `CORS_ORIGINS` | localhost | Allowed browser origins |
| `NEXT_PUBLIC_API_URL`, `API_URL` | | Where the browser and the Next server find the API |
| `NEXT_PUBLIC_TILE_URL`, `NEXT_PUBLIC_TILE_ATTRIBUTION` | OSM | Map tiles, if you self-host them |

## Privacy

- Reports are reachable only by their random id. There is no public list of uploads.
- Untagged reports expire after an hour. The same log uploaded again within that hour returns the
  existing report.
- Tagging a flight with an airframe label keeps it for that airframe's trends. The first write to an
  airframe returns an **airframe token**, shown once. Keep it: reading or changing that airframe's
  config, maintenance log, applied changes, trends or record PDF needs it (`X-Airframe-Token`).
  The browser remembers it, and you can paste it on another device.
- "Contribute this log" is off by default. If you tick it, the raw log is kept along with a report
  stripped of the file name, place name and GPS track; the raw log itself still contains its GPS
  data. The upload returns a contribution id, and `DELETE /dataset/{id}` (or the button in the
  browser) withdraws both.
- The Q&A sees the report only, never the raw log, and answers "Not in this report" when it can't
  find the answer there.
- `/metrics` carries counts and timings only: no file names, coordinates or ids.

On Render's free plan the disk is wiped on every deploy or restart. Attach a disk, or self-host
with a volume, if you need history to stick.

## Modules

| Module | Looks at | Weight |
|---|---|---|
| Oscillation | Rate-loop oscillation from 4 s spectrogram windows, by band (P, D or mechanical); setpoint vs actual where logged | 20 % |
| Vibration | The autopilot's vibration metric and clip counters first (PX4 4.9/9.8 m/s², ArduPilot 30/60 m/s²), raw IMU otherwise | 20 % |
| EKF | Test ratios on one scale (1.0 = rejected, warning above 0.64 sustained), solution and fault flags | 20 % |
| Battery | Internal resistance per window, C-rate against rated capacity, cells, temperature | 15 % |
| GPS | Fix loss, HDOP, satellites, jamming and spoofing state, sustained for 2 s | 15 % |
| Parameters | Firmware metadata ranges, tighter safe ranges where they matter, risky combinations | 5 % |
| Motors | Per-motor balance at hover, real ESC dropouts | 5 % |
| Power supply | Board 5 V rail and power flags | not scored |
| Ascent & Recovery | Apogee, boost and parachute deployment for rockets and balloons | not scored |

Advice is vehicle-aware: multicopter rate-gain advice isn't given to fixed-wing, VTOL or rover
logs. A module that can't run is left out of the score and shown as "Not assessed".

New analysers can be added as plugins without touching the core: see
[`docs/plugins.md`](docs/plugins.md).

## Report schema

The report format is versioned (currently 1.7) and published as JSON Schema in
[`docs/schema/`](docs/schema/), with a changelog. To change it, bump `schema_version`, run
`python scripts/export_schema.py` and add a changelog entry. `tests/test_schema.py` fails if the
published file and the model drift apart.

Parameter tables are generated from the official metadata with
`python scripts/gen_param_tables.py`.

## Accuracy

[`verification/VERIFICATION_REPORT.md`](verification/VERIFICATION_REPORT.md) covers 50 public logs
from PX4 Flight Review (11 vehicle types, 8.4 GB). It was written against the July 2026 engine,
before the October 2026 rework, so its per-finding numbers are out of date; the regression corpus
above is its replacement going forward.

## Layout

```
flightmd_core/   analysis engine: parsers, analysers, exporters, CLI (pip install flightmd-core)
api/             FastAPI service, SQLite store, job queue
frontend/        Next.js app
tests/           pytest, sample logs, real-log corpus
docs/            report schema, plugin guide
verification/    the 50-log run
```

## Deploying

The API runs on Render (`api/render.yaml`) or anywhere Docker runs (`docker build -f api/Dockerfile .`
from the repo root); the frontend on Vercel (`frontend/vercel.json`) or the Compose `web` service.
CI tests Python 3.11–3.13, the frontend, a Playwright smoke test and a bundle-size budget, and only
then deploys. Tagging `vX.Y.Z` publishes `flightmd-core` to PyPI through Trusted Publishing.

## Part of the UAV suite

FlightMD · AeroAtlas (airspace and site planning) · [UAOP](https://github.com/Praddyx15/UAOP)
(ground control station). All three share one design system and one token file. UAOP runs
FlightMD as its flight-log engine, and AeroAtlas reads FlightMD reports for its flight audit; a
report uploaded with an AeroAtlas brief hash links back to the plan it flew.

## License

MIT, see [LICENSE](LICENSE). Built by [Pradum Behl](https://github.com/Praddyx15).
