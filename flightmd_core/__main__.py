import argparse
import asyncio
import os
import sys

from flightmd_core.orchestrator import run_analysis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m flightmd_core",
        description="Analyse a PX4 .ulg, ArduPilot .bin or MAVLink .tlog flight log.",
    )
    ap.add_argument("log")
    ap.add_argument("--json", metavar="OUT", help="write the full report to this JSON file")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.log):
        ap.error(f"no such file: {args.log}")

    # local runs stay local unless asked otherwise (FLIGHTMD_OFFLINE=0)
    os.environ.setdefault("FLIGHTMD_OFFLINE", "1")

    try:
        report = asyncio.run(run_analysis(
            ulog_path=args.log,
            file_name=os.path.basename(args.log),
            file_size=os.path.getsize(args.log),
        ))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # print(report.metadata.available_topics)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

    print(f"{report.file_name}: {report.overall_score:.0f}/100 ({report.letter_grade}, {report.score_label})")
    for w in report.metadata.parse_warnings:
        print(f"  note: {w}")
    for f in report.findings:
        print(f"  [{f.severity.upper()}] {f.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
