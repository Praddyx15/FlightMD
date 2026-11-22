# StrictDoc project config for the requirement documents under docs/lifecycle.
# Run from the repo root:
#   strictdoc export docs/lifecycle --config docs/lifecycle/08-traceability/strictdoc_config.py
#       --output-dir .local/strictdoc --formats html --no-parallelization
# or simply: python tools/trace.py --html
# The output stays in .local (not tracked); the committed trace is matrix.md beside this file.

from pathlib import Path

from strictdoc.core.project_config import ProjectConfig

REPO = Path(__file__).resolve().parents[3]


def create_config() -> ProjectConfig:
    return ProjectConfig(
        project_title="FlightMD requirements and trace",
        dir_for_sdoc_cache=str(REPO / ".local" / "cache" / "strictdoc"),
        project_features=["TABLE_SCREEN", "TRACEABILITY_SCREEN", "DEEP_TRACEABILITY_SCREEN",
                          "TRACEABILITY_MATRIX_SCREEN", "SEARCH", "REQUIREMENT_TO_SOURCE_TRACEABILITY"],
        # relative to the input folder, docs/lifecycle
        grammars={"@flightmd": "02-standards/requirements.sgra"},
        # StrictDoc would read the Markdown documents beside the .sdoc files as its own
        exclude_doc_paths=["*.md"],
        # the code that carries @relation(LLR-..., scope=...) tags; same folders as tools/trace.py
        source_root_path=str(REPO),
        include_source_paths=["flightmd_core/**", "api/**", "scripts/*.py", "frontend/lib/**",
                              "frontend/components/**", "frontend/app/**", "frontend/i18n/**"],
        exclude_source_paths=["**/__pycache__/**", "**/node_modules/**", "**/*.json", "**/*.html", "**/*.css"],
    )
