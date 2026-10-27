"""
Regression corpus: real public logs (tests/corpus/manifest.json) run through the whole
pipeline offline and compared with reviewed golden results in tests/corpus/golden/.

    pytest -m corpus                    compare against the goldens
    pytest -m corpus --update-golden    rewrite them (then review the diff by hand)

Logs are downloaded on first use into $FLIGHTMD_CORPUS_DIR (default tests/corpus/logs)
and checked against the manifest's sha256.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import flightmd_core
from flightmd_core.orchestrator import run_analysis

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
GOLDEN_DIR = HERE / "golden"
EXT = {"px4_ulog": ".ulg", "ardupilot_bin": ".bin", "mavlink_tlog": ".tlog"}

SCORE_BAND = 5.0
METRIC_REL_TOL = 0.10
METRIC_ABS_TOL = 0.05


def corpus_dir() -> Path:
    return Path(os.environ.get("FLIGHTMD_CORPUS_DIR") or HERE / "logs")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(entry) -> Path:
    """The log on disk, downloading it if needed. Skips when it can't be downloaded."""
    path = corpus_dir() / f"{entry['id']}{EXT.get(entry['format'], '.log')}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        try:
            req = urllib.request.Request(entry["url"], headers={"User-Agent": "flightmd-corpus-test"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as f:
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
        except (urllib.error.URLError, OSError) as e:
            part.unlink(missing_ok=True)
            pytest.skip(f"{entry['id']}: download unavailable ({e})")
        os.replace(part, path)

    digest = sha256_of(path)
    if digest != entry["sha256"]:
        path.unlink()
        pytest.fail(f"{entry['id']}: sha256 {digest} != manifest {entry['sha256']}; "
                    f"the file at {entry['url']} changed")
    return path


def summarise(report) -> dict:
    """The parts of a report the goldens pin down."""
    assessed = sorted(
        r.analyser for r in report.analyser_results
        if not r.skipped and getattr(r, "assessed", True)
    )
    metrics = {}
    for r in report.analyser_results:
        for k, v in (r.key_metrics or {}).items():
            if v is not None:
                metrics[f"{r.analyser}.{k}"] = round(float(v), 4)
    md = report.metadata
    return {
        "score": report.overall_score,
        "findings": sorted({f"{f.kind or f.title}|{getattr(f.severity, 'value', f.severity)}" for f in report.findings}),
        "assessed_modules": assessed,
        "metrics": dict(sorted(metrics.items())),
        "metadata": {
            "source_format": md.source_format,
            "vehicle_type": md.vehicle_type,
            "airframe_name": md.airframe_name,
            "firmware_version": md.firmware_version,
            "px4_version": md.px4_version,
            "duration_seconds": md.duration_seconds,
        },
    }


@pytest.mark.corpus
@pytest.mark.asyncio
@pytest.mark.parametrize("entry", MANIFEST["logs"], ids=lambda e: e["id"])
async def test_corpus_log_matches_golden(entry, request):
    golden_path = GOLDEN_DIR / f"{entry['id']}.json"
    update = request.config.getoption("--update-golden")
    if not update and not golden_path.exists():
        pytest.skip(f"no golden for {entry['id']}; generate it with pytest -m corpus --update-golden "
                    f"and review it (tests/corpus/golden/README.md)")

    path = fetch(entry)
    report = await run_analysis(ulog_path=str(path), file_name=path.name, file_size=path.stat().st_size)
    got = summarise(report)
    assert got["metadata"]["source_format"] == entry["format"]

    if update:
        golden = {
            "id": entry["id"],
            "generated_with": flightmd_core.__version__,
            "schema_version": report.schema_version,
            "score_band": [round(got["score"] - SCORE_BAND, 1), round(got["score"] + SCORE_BAND, 1)],
            **got,
        }
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(golden, indent=2) + "\n", encoding="utf-8", newline="\n")
        return

    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    lo, hi = golden["score_band"]
    assert lo <= got["score"] <= hi, f"score {got['score']} outside {lo}-{hi}"
    assert got["findings"] == golden["findings"]
    assert got["assessed_modules"] == golden["assessed_modules"]

    tolerances = golden.get("tolerances", {})
    for key, expected in golden["metrics"].items():
        assert key in got["metrics"], f"metric {key} is gone"
        tol = tolerances.get(key, {})
        assert got["metrics"][key] == pytest.approx(
            expected, rel=tol.get("rel", METRIC_REL_TOL), abs=tol.get("abs", METRIC_ABS_TOL)
        ), key

    for key, expected in golden.get("metadata", {}).items():
        if key == "duration_seconds":
            assert got["metadata"][key] == pytest.approx(expected, abs=1.0)
        else:
            assert got["metadata"][key] == expected, key


def test_manifest_is_well_formed():
    ids = [e["id"] for e in MANIFEST["logs"]]
    assert len(ids) == len(set(ids))
    assert 10 <= len(ids) <= 20
    for e in MANIFEST["logs"]:
        assert e["format"] in EXT
        assert len(e["sha256"]) == 64 and int(e["sha256"], 16) >= 0
        assert e["size"] > 0
        assert e["url"].startswith("https://")
        assert e["vehicle"] and e["firmware"]
