import argparse
import asyncio
import json
import os
import sys
from typing import Optional

from flightmd_core.orchestrator import run_analysis

COMMANDS = ("analyse", "compare")


def _write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _show_progress(pct: int, msg: str, eta_s=None) -> None:
    left = f"  ~{eta_s:.0f} s left" if eta_s else ""
    # pad so a shorter line wipes the end of the last one
    sys.stderr.write(f"\r[{pct:3d}%] {msg}{left}".ljust(79))
    if pct >= 100:
        sys.stderr.write("\n")
    sys.stderr.flush()


def analyse(args) -> int:
    if not os.path.isfile(args.log):
        print(f"error: no such file: {args.log}", file=sys.stderr)
        return 2

    # local runs stay local unless asked otherwise
    if args.offline is None:
        os.environ.setdefault("FLIGHTMD_OFFLINE", "1")
    else:
        os.environ["FLIGHTMD_OFFLINE"] = "1" if args.offline else "0"

    try:
        report = asyncio.run(run_analysis(
            ulog_path=args.log,
            file_name=os.path.basename(args.log),
            file_size=os.path.getsize(args.log),
            progress_callback=_show_progress if sys.stderr.isatty() else None,
        ))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        _write(args.json, report.model_dump_json(indent=2).encode("utf-8"))
    if args.gpx or args.kml:
        from flightmd_core.services.geo_export import generate_gpx, generate_kml

        if args.gpx:
            _write(args.gpx, generate_gpx(report))
        if args.kml:
            _write(args.kml, generate_kml(report))
    if args.pdf:
        from flightmd_core.exporters.pdf import render_report_pdf

        try:
            _write(args.pdf, render_report_pdf(report))
        except RuntimeError as e:
            # WeasyPrint missing: everything else was still written
            print(f"error: no PDF: {e}", file=sys.stderr)
            return 3

    print(f"{report.file_name}: {report.overall_score:.0f}/100 ({report.letter_grade}, {report.score_label})")
    for w in report.metadata.parse_warnings:
        print(f"  note: {w}")
    for f in report.findings:
        print(f"  [{f.severity.upper()}] {f.title}")
    return 0


def _finding_key(f: dict) -> tuple:
    # kind is stable across runs; older reports only have the title
    return (f.get("kind") or f.get("title"), f.get("severity"))


def _module_score(m: Optional[dict]) -> Optional[float]:
    if m is None or m.get("skipped") or m.get("assessed") is False:
        return None
    return m.get("health_score")


def compare_reports(a: dict, b: dict) -> dict:
    """What changed from report a (before) to report b (after)."""
    ma = {m["analyser"]: m for m in a.get("analyser_results", [])}
    mb = {m["analyser"]: m for m in b.get("analyser_results", [])}
    module_deltas = {}
    for name in sorted(set(ma) | set(mb)):
        sa, sb = _module_score(ma.get(name)), _module_score(mb.get(name))
        module_deltas[name] = {
            "before": sa,
            "after": sb,
            "delta": round(sb - sa, 1) if sa is not None and sb is not None else None,
        }

    fa = {_finding_key(f): f for f in a.get("findings", [])}
    fb = {_finding_key(f): f for f in b.get("findings", [])}
    return {
        "before": a.get("file_name"),
        "after": b.get("file_name"),
        "score_before": a.get("overall_score"),
        "score_after": b.get("overall_score"),
        "score_delta": round(b.get("overall_score", 0) - a.get("overall_score", 0), 1),
        "modules": module_deltas,
        "findings_resolved": [fa[k]["title"] for k in fa if k not in fb],
        "findings_new": [fb[k]["title"] for k in fb if k not in fa],
    }


def compare(args) -> int:
    reports = []
    for p in (args.before, args.after):
        try:
            with open(p, encoding="utf-8") as f:
                reports.append(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: can't read {p}: {e}", file=sys.stderr)
            return 2

    diff = compare_reports(*reports)
    print(f"{diff['before']} -> {diff['after']}")
    print(f"  score {diff['score_before']:.0f} -> {diff['score_after']:.0f} ({diff['score_delta']:+.0f})")
    for name, m in diff["modules"].items():
        if m["delta"] is None:
            before = "-" if m["before"] is None else f"{m['before']:.0f}"
            after = "-" if m["after"] is None else f"{m['after']:.0f}"
            print(f"  {name}: {before} -> {after}")
        elif m["delta"]:
            print(f"  {name}: {m['before']:.0f} -> {m['after']:.0f} ({m['delta']:+.0f})")
    for t in diff["findings_resolved"]:
        print(f"  resolved: {t}")
    for t in diff["findings_new"]:
        print(f"  new:      {t}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `flightmd flight.ulg --json x` from before the subcommands still works
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "analyse")

    ap = argparse.ArgumentParser(
        prog="flightmd",
        description="Flight log health checks for PX4, ArduPilot and MAVLink logs.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyse", help="analyse one log")
    a.add_argument("log", help=".ulg, .bin, .log, .tlog, .bbl, DJI .txt/.DAT, or any of them .gz/.zip")
    a.add_argument("--json", metavar="FILE", help="write the full report as JSON")
    a.add_argument("--pdf", metavar="FILE", help="write the PDF report (needs flightmd-core[pdf])")
    a.add_argument("--gpx", metavar="FILE", help="write the flight path as GPX")
    a.add_argument("--kml", metavar="FILE", help="write the flight path as KML")
    net = a.add_mutually_exclusive_group()
    net.add_argument("--offline", dest="offline", action="store_true", default=None,
                     help="no weather, geocoding or AI calls (the default)")
    net.add_argument("--online", dest="offline", action="store_false",
                     help="look up weather and place name")
    a.set_defaults(func=analyse)

    c = sub.add_parser("compare", help="compare two report JSON files (before, after)")
    c.add_argument("before")
    c.add_argument("after")
    c.set_defaults(func=compare)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
