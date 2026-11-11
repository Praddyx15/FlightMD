"""
Writes docs/schema/flightmd-report-<schema_version>.json from the report model.
Run it after changing flightmd_core/models (and bumping schema_version), then
add a line to docs/schema/CHANGELOG.md. tests/test_schema.py fails until the
published file matches the model again.

    python scripts/export_schema.py
"""

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from flightmd_core.models.findings import FlightMDReport  # noqa: E402

version = FlightMDReport.model_fields["schema_version"].default
path = os.path.join(ROOT, "docs", "schema", f"flightmd-report-{version}.json")
os.makedirs(os.path.dirname(path), exist_ok=True)

tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8", newline="\n") as f:
    json.dump(FlightMDReport.model_json_schema(), f, indent=2)
    f.write("\n")
os.replace(tmp, path)
print(path)
