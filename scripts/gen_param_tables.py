"""
Builds flightmd_core/data/param_tables/*.json from the autopilots' own parameter
metadata: PX4 parameters.xml per release, ArduPilot apm.pdef.xml per vehicle for the
current stable and the series before it.

Each file maps a parameter name to whatever the metadata gives of
default, min, max, unit, type, reboot_required. ArduPilot's metadata has no
defaults (they live in the C++), so its tables don't either.

Run: python scripts/gen_param_tables.py      (needs network; writes in place)
"""

import base64
import json
import math
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import date

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "flightmd_core", "data", "param_tables")

# PX4 publishes parameters.xml inside each board's .px4 (zlib + base64) and, for some
# tags, as a plain file on its S3 bucket. fmu-v6x default has the widest module set.
PX4_SOURCES = {
    "1.13.3": [
        "https://github.com/PX4/PX4-Autopilot/releases/download/v1.13.3/px4_fmu-v6x_default.px4",
    ],
    "1.14.0": [
        "https://px4-travis.s3.amazonaws.com/Firmware/v1.14.0/px4_fmu-v6x_default/parameters.xml",
    ],
    "1.15.0": [
        "https://github.com/PX4/PX4-Autopilot/releases/download/v1.15.0/px4_fmu-v6x_default.px4",
        "https://px4-travis.s3.amazonaws.com/Firmware/v1.15.0/px4_fmu-v6x_default.px4",
    ],
}

AP_INDEX = "https://autotest.ardupilot.org/Parameters/versioned/{vehicle}/"
AP_PDEF = "https://autotest.ardupilot.org/Parameters/versioned/{vehicle}/{tag}/apm.pdef.xml"
AP_VEHICLES = ["Copter", "Plane", "Rover"]
AP_SERIES = 2       # current stable series + the one before


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FlightMD gen_param_tables"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def num(s):
    if s is None:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return int(v) if v.is_integer() and "." not in s and "e" not in s.lower() else v


def px4_xml(url: str) -> bytes:
    raw = fetch(url)
    if url.endswith(".px4"):
        return zlib.decompress(base64.b64decode(json.loads(raw)["parameter_xml"]))
    return raw


def parse_px4(xml: bytes) -> dict:
    out = {}
    for p in ET.fromstring(xml).iter("parameter"):
        e = {
            "default": num(p.get("default")),
            "min": num(p.findtext("min")),
            "max": num(p.findtext("max")),
            "unit": p.findtext("unit") or None,
            "type": p.get("type"),
            "reboot_required": (p.findtext("reboot_required") or "").strip() == "true",
        }
        if p.get("boolean") == "true":
            e["type"] = "BOOL"
        out[p.get("name")] = {k: v for k, v in e.items() if v is not None and v is not False}
    return out


def parse_pdef(xml: bytes) -> dict:
    out = {}
    for p in ET.fromstring(xml).iter("param"):
        name = p.get("name").split(":")[-1]
        fields = {f.get("name"): (f.text or "").strip() for f in p.findall("field")}
        e = {}
        rng = fields.get("Range", "").split()
        if len(rng) == 2 and num(rng[0]) is not None and num(rng[1]) is not None:
            e["min"], e["max"] = num(rng[0]), num(rng[1])
        if fields.get("Units"):
            e["unit"] = fields["Units"]
        if "Bitmask" in fields:
            e["type"] = "bitmask"
        elif p.find("values") is not None:
            e["type"] = "enum"
        if fields.get("RebootRequired", "").lower() == "true":
            e["reboot_required"] = True
        if fields.get("ReadOnly", "").lower() == "true":
            e["read_only"] = True

        prev = out.get(name)
        if prev and "min" in prev and "min" in e:
            # same name documented twice (multicopter and heli attitude control):
            # take the wider range so neither airframe gets a false finding
            e["min"], e["max"] = min(prev["min"], e["min"]), max(prev["max"], e["max"])
        elif prev and "min" in prev:
            e["min"], e["max"] = prev["min"], prev["max"]
        out[name] = {**(prev or {}), **e}
    return out


def ap_tags(vehicle: str) -> list[str]:
    html = fetch(AP_INDEX.format(vehicle=vehicle)).decode("utf-8", "replace")
    tags = set(re.findall(r'href="(stable-\d+\.\d+\.\d+)/"', html))
    latest = {}
    for t in tags:
        v = tuple(int(x) for x in t.split("-")[1].split("."))
        if v > latest.get(v[:2], (0,)):
            latest[v[:2]] = v
    keep = sorted(latest)[-AP_SERIES:]
    return ["stable-" + ".".join(map(str, latest[s])) for s in keep]


def write(path: str, header: dict, params: dict) -> None:
    # one parameter per line so a regenerated table diffs cleanly
    lines = [json.dumps(k) + ": " + json.dumps(params[k], ensure_ascii=False) for k in sorted(params)]
    body = json.dumps(header, indent=2, ensure_ascii=False)[:-2]
    text = body + ',\n  "params": {\n    ' + ",\n    ".join(lines) + "\n  }\n}\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    today = date.today().isoformat()
    failed = []

    for version, urls in PX4_SOURCES.items():
        params = None
        for url in urls:
            try:
                params = parse_px4(px4_xml(url))
                break
            except Exception as e:
                print(f"px4 {version}: {url}: {e}", file=sys.stderr)
        if not params:
            failed.append(f"px4 {version}")
            continue
        series = ".".join(version.split(".")[:2])
        write(os.path.join(OUT_DIR, f"px4_{series}.json"),
              {"autopilot": "px4", "vehicle": None, "version": version, "source": url, "generated": today},
              params)
        print(f"px4 {version}: {len(params)} params")

    for vehicle in AP_VEHICLES:
        try:
            tags = ap_tags(vehicle)
        except Exception as e:
            print(f"ardupilot {vehicle}: index: {e}", file=sys.stderr)
            failed.append(f"ardupilot {vehicle}")
            continue
        for tag in tags:
            url = AP_PDEF.format(vehicle=vehicle, tag=tag)
            try:
                params = parse_pdef(fetch(url))
            except Exception as e:
                print(f"ardupilot {vehicle} {tag}: {e}", file=sys.stderr)
                failed.append(f"ardupilot {vehicle} {tag}")
                continue
            version = tag.split("-")[1]
            series = ".".join(version.split(".")[:2])
            write(os.path.join(OUT_DIR, f"ardupilot_{vehicle.lower()}_{series}.json"),
                  {"autopilot": "ardupilot", "vehicle": vehicle.lower(), "version": version,
                   "source": url, "generated": today},
                  params)
            print(f"ardupilot {vehicle} {version}: {len(params)} params")

    if failed:
        print("failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
