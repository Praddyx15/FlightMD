# FlightMD ✈️

**Your drone's flight log, decoded.**

FlightMD is a production-grade, open-source PX4 ULog flight log analyser that generates plain-English AI diagnostic reports for drone pilots and engineers.

[![CI](https://github.com/sixtymotion/flightmd/actions/workflows/ci.yml/badge.svg)](https://github.com/sixtymotion/flightmd/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## What it does

Upload a PX4 `.ulg` (ULog) file. Within 20 seconds you receive a structured diagnostic report:

- **Overall health score** (0–100) with label
- **Categorised findings** — oscillation, vibration, EKF, battery, GPS, parameters, motors
- **Plain-English explanations** of every issue (Claude AI-powered)
- **Exact parameter changes** to fix each problem (copy-pasteable)
- **PDF export** for DGCA compliance records

## Who is it for

- Commercial drone pilots who stare at log graphs without knowing what they mean
- UAV engineers tuning new airframes
- Fleet operators who need post-flight health checks before the next day
- Students learning PX4 tuning

## Live Demo

- **Frontend**: [https://flightmd.vercel.app](https://flightmd.vercel.app)
- **API**: [https://flightmd-api.onrender.com](https://flightmd-api.onrender.com)
- **API Docs**: [https://flightmd-api.onrender.com/docs](https://flightmd-api.onrender.com/docs)

---

## Repository Structure

```
flightmd/
├── flightmd_core/     ← Pure Python analysis package (pip-installable)
├── api/               ← FastAPI web service
├── frontend/          ← Next.js 14 web app
└── tests/             ← pytest test suite
```

## Quick Start

### Backend (API)

```bash
cd api
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### Using `flightmd_core` as a Python package

```python
from flightmd_core import run_analysis

report = await run_analysis(
    ulog_path="flight.ulg",
    file_name="flight.ulg",
    file_size=1234567,
    anthropic_api_key="your_key_here",
)
print(f"Health: {report.overall_score}/100 ({report.score_label})")
for finding in report.findings:
    print(f"[{finding.severity}] {finding.title}")
    print(f"  → {finding.plain_english}")
```

## Analysis Modules

| Module | What it checks | Weight |
|--------|---------------|--------|
| Oscillation | FFT-based roll/pitch/yaw oscillation detection | 20% |
| Vibration | IMU RMS + clip analysis | 20% |
| EKF | Innovation spikes, solution validity flags | 20% |
| Battery | Voltage sag, IR estimation, capacity fade | 15% |
| GPS | Fix quality, HDOP, jamming, spoofing | 15% |
| Parameters | Anomalies vs PX4 defaults, dangerous combos | 5% |
| Motors | ESC telemetry, motor balance, RPM dropouts | 5% |

## UAOP Integration

`flightmd_core` is architecturally designed to be imported directly by UAOP (Unified Autonomy Operating Platform) as a Python package dependency:

```toml
# In UAOP's pyproject.toml
dependencies = [
    "flightmd-core>=1.0.0",
]
```

The `FlightMDReport` data contract (`schema_version = "1.0"`) will remain stable across minor versions.

## Deployment

- **Backend**: Render.com free tier (Singapore region)
- **Frontend**: Vercel free tier
- **CI/CD**: GitHub Actions

See `api/render.yaml` and `frontend/vercel.json` for deployment configs.

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Run tests: `cd api && pytest ../tests/ -v`
4. Submit a PR

## License

MIT — see [LICENSE](LICENSE)

---

*Built by [Sixty Motion Aerospace](https://sixtymotion.aero), India*
