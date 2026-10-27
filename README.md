# FlightMD

Flight log analysis for PX4, ArduPilot and MAVLink, in plain English.

[![CI](https://github.com/Praddyx15/FlightMD/actions/workflows/ci.yml/badge.svg)](https://github.com/Praddyx15/FlightMD/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Drop in a `.ulg`, `.bin` or `.tlog` and FlightMD tells you what went wrong in the flight, why, and
which parameter to change. The format is detected from the file contents, not the extension.

Every finding comes from a deterministic rule engine, so the same log always gives the same report
and every severity can be traced to a threshold in the code. An AI layer is optional. When it's
switched on it only rewrites the executive summary and answers questions about the report; it never
adds or changes a finding.

## What you get

- A health score (0–100, A–F) weighted across the modules that could actually be assessed. A log
  with no usable telemetry says "Not assessed" instead of pretending to be a perfect flight.
- Findings for oscillation, vibration, EKF, battery, GPS, parameters and motors, each with a
  plain-English explanation, a time window you can jump to on the charts, and a confidence level.
- Checks run on the part of the log where the vehicle was armed or in the air, so GPS acquisition
  on the pad or motors spinning down after landing don't show up as faults. Logs without arming
  data fall back to the whole log, and the report says so.
- A parameter change sheet you can paste straight into Mission Planner (`NAME,VALUE`) or load into
  QGroundControl (tab-separated with the QGC header).
- Exports: PDF (or just print the page), JSON, GPX and KML.
- Opt-in per-airframe history: trends across flights, maintenance log, pre-flight checklist and
  webhook alerts (Slack/Discord) when a flight breaks a rule you set.
- Side-by-side comparison of two flights.
- A dark "ops" theme and a light "field" theme for laptops in sunlight.

## Run it

Python 3.11+ and Node 20+.

### API

```bash
pip install -r api/requirements.txt
python -m uvicorn api.main:app --reload
```

Run it from the repo root, not from `api/`; the app imports its modules as `api.*`.

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### Command line

No server needed. Runs offline by default.

```bash
pip install -e .
python -m flightmd_core flight.ulg --json report.json
```

Set `FLIGHTMD_OFFLINE=0` if you want weather and place names looked up.

### As a library

```python
from flightmd_core import run_analysis

report = await run_analysis(ulog_path="flight.ulg", file_name="flight.ulg", file_size=1234567)
print(report.overall_score, report.score_label)
for f in report.findings:
    print(f.severity, f.title, f.t_start_s)
```

Pass `ai_enhancer=AIEnhancer(...)` from `flightmd_core.services.ai_enhancer` to get the polished
summary. `run_analysis` raises `ValueError` for anything it can't analyse (unknown format, too big,
no telemetry, parse timeout).

### Tests

```bash
pip install -r api/requirements.txt -r api/requirements-dev.txt
pytest -m "not integration"     # unit tests
pytest                          # also runs the sample logs in tests/sample_logs/
```

## Configuration

Everything is optional. See [`.env.example`](.env.example) for the full list.

| Variable | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | `groq` | `groq` (free tier) or `anthropic` |
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | | Turns on the AI summary and Q&A |
| `FLIGHTMD_OFFLINE` | `0` (API), `1` (CLI) | Skip weather, reverse geocoding and AI |
| `FLIGHTMD_MAX_LOG_MB` | `512` | Biggest log the engine will open |
| `FLIGHTMD_PARSE_TIMEOUT_S` | `600` | Parse in a child process and stop it after this. `0` parses in-process, which uses less memory on small instances |
| `MAX_FILE_SIZE_MB` | `50` | Upload limit on the API |
| `MAX_CONCURRENT_ANALYSES` | `2` | Analyses running at once; further uploads get a 503 |
| `RATE_LIMIT_PER_HOUR`, `ASK_RATE_LIMIT_PER_HOUR`, `PDF_RATE_LIMIT_PER_HOUR` | `10`, `30`, `30` | Per client IP |
| `TRUSTED_PROXIES` | empty | Proxies whose `X-Forwarded-For` is believed. Leave empty unless you run behind one |
| `ALLOW_HTTP_WEBHOOKS` | `false` | Alert webhooks are https-only otherwise |
| `CORS_ORIGINS` | localhost | Allowed browser origins |
| `NEXT_PUBLIC_API_URL` | | Where the frontend finds the API |
| `NEXT_PUBLIC_TILE_URL`, `NEXT_PUBLIC_TILE_ATTRIBUTION` | OSM | Map tiles, if you self-host them |

## Privacy

- Reports are reachable only by their random id. There is no public list of uploads.
- Untagged reports expire after an hour.
- Tagging a flight with an airframe label keeps it for that airframe's trends. The first write to an
  airframe returns an **airframe token**, shown once. Keep it: every later read or change of that
  airframe's config, maintenance log, trends or record PDF needs it (`X-Airframe-Token` header).
  The browser remembers it for you, and you can paste it on another device.
- "Contribute this log" is off by default. If you tick it, the report is stored without the file
  name, place name or GPS track, but the raw log itself still contains its GPS data.
- The Q&A sees the report only, never the raw log, and answers "Not in this report" when it can't
  find the answer there.

On a free Render instance the disk is wiped on every deploy or restart, so nothing there is
permanent. Self-host with a volume if you need history to stick.

## Modules

| Module | Looks at | Weight |
|---|---|---|
| Oscillation | Rate-loop oscillation from 4 s spectrogram windows, by frequency band (P, D or mechanical) | 20 % |
| Vibration | High-passed IMU RMS per IMU, real clipping from the autopilot's clip counters | 20 % |
| EKF | Innovation test ratios and solution flags, PX4 bit layout | 20 % |
| Battery | Internal resistance per window (what "sag" means here), C-rate against rated capacity, temperature | 15 % |
| GPS | Fix loss, HDOP, satellites, jamming and spoofing state, sustained for 2 s | 15 % |
| Parameters | Values against PX4 defaults and safe ranges, risky combinations (PX4 only) | 5 % |
| Motors | Per-motor balance at hover, real ESC dropouts (one motor stops while the others fly) | 5 % |

Advice is vehicle-aware: multicopter rate-gain advice isn't given to fixed-wing, VTOL or rover logs.

A module that can't run (missing topics) is left out of the score and shown as "Not assessed".

### Ascent & Recovery

An eighth module for sounding rockets and high-altitude balloons. It finds a single dominant
climb-and-descend profile in the altitude trace and reports apogee, the boost phase and parachute
deployment, including a likely chute failure. It isn't weighted into the score, because it doesn't
apply to normal drone flights.

## Accuracy

[`verification/VERIFICATION_REPORT.md`](verification/VERIFICATION_REPORT.md) covers 50 public logs
from PX4 Flight Review (11 vehicle types, 8.4 GB). It was written against the July 2026 engine,
before the October 2026 rework of flight-phase gating, EKF bit maps, battery and oscillation maths,
so its per-finding numbers are out of date. Re-running it is on the list.

Things to know:

- Parameter checks know PX4 v1.13–v1.14 defaults. ArduPilot logs get every other module.
- tlogs are filtered to the autopilot's system id; GCS and companion traffic is ignored.
- Betaflight, DJI and ArduPilot text `.log` files aren't supported yet.

## Layout

```
flightmd_core/   analysis engine (parsers, analysers, report model), pip-installable
api/             FastAPI service
frontend/        Next.js app
tests/           pytest, with sample logs for all three formats
verification/    the 50-log run
```

## Deploying

The API runs on Render (`api/render.yaml`, or `docker build -f api/Dockerfile .` from the repo root)
and the frontend on Vercel (`frontend/vercel.json`). CI deploys only after the test job passes.

## Part of the UAV suite

FlightMD · AeroAtlas (airspace and site planning) · [UAOP](https://github.com/Praddyx15/UAOP)
(ground control station). All three share one design system: the same blue accent, cool neutrals,
aviation colour meanings and Geist type.

## License

MIT, see [LICENSE](LICENSE). Built by [Pradum Behl](https://github.com/Praddyx15).
