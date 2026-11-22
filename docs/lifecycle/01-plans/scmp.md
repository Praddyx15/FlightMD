# Software configuration management plan

FMD-SCMP, issue 1, 2026-11-20. How FlightMD's configuration items are
identified, baselined, changed and released. Configuration management is git
and GitHub, as the repository already uses them.

## 1. Configuration items

| Item | Where | Identified by |
|---|---|---|
| Source code | `flightmd_core/`, `api/`, `frontend/`, `scripts/`, `tools/` | Git commit |
| Shipped data | `flightmd_core/data/` (parameter tables named by firmware and version, safe ranges, airframe names) | Git commit; table file name |
| Tests and test data | `tests/` (sample logs, corpus manifest and golden results), `frontend/test`, `frontend/e2e` | Git commit. The corpus logs themselves are downloaded, not committed; `tests/corpus/manifest.json` names each with its source and hash |
| Lifecycle data | `docs/lifecycle/`; each document carries an id, issue and date | Git commit |
| Report schema | `docs/schema/flightmd-report-<version>.json`, `docs/schema/CHANGELOG.md` | `schema_version` in every report |
| Python dependencies | `pyproject.toml`, `api/requirements.txt`, `api/requirements-dev.txt`, `api/requirements.lock` when generated | Versions in those files |
| Web dependencies | `frontend/package-lock.json` | Integrity hashes in the lock file |
| Build and deployment | `api/Dockerfile`, `docker-compose.yml`, `api/render.yaml`, `frontend/vercel.json`, `.github/workflows/` | Git commit; actions pinned to commit SHAs |

Not configuration items, and ignored by git: virtual environments,
`node_modules`, build output, caches, `.local/` (StrictDoc HTML), run-time
data (`data/`), `.env` files and downloaded corpus logs.

## 2. Branches and baselines

- `main` is the released line. `dev` is the integration branch; topic
  branches are named for their purpose (`docs/lifecycle`).
- Changes reach `main` by pull request only, after CI passes.
- A **baseline** is a commit on `main`. A **release baseline** is a tag
  `vX.Y.Z` on `main`; `publish.yml` refuses a tag that does not match the
  package version, runs CI again, builds the sdist and wheel and publishes
  them.
- The report format has its own version (`schema_version`), bumped by the
  rule in the design standard (DS-10) whatever the package version does.
- The parse cache has its own version (`CACHE_VERSION` in
  `flightmd_core/cache.py`), bumped when a parser change makes old entries
  wrong.

## 3. Change control

| Kind of change | Record | Needs before merge |
|---|---|---|
| Defect | A row in `10-configuration/problem-reports.md` (and a GitHub issue if reported from outside) | A test that fails without the fix; the row updated |
| New or changed behaviour | The HLR/LLR change in the same pull request | Tests naming the requirements; trace check green |
| A threshold or a rule of a check | The LLR that states it (requirements standard RS-18) | Corpus run; changed golden results reviewed one by one and committed with the reason |
| Report schema | `schema_version`, the exported schema, the changelog | `tests/test_schema.py` |
| Parameter tables | The regenerated JSON | The diff read; firmware version and source noted in the pull request |
| Dependency | The requirements or lock file | CI including `pip-audit` |
| Lifecycle documents | The document's issue and date | Review checklist |

Commit messages follow the repository's habit: a short subject, optionally
prefixed `fix:`, `test:`, `docs:`, `ci:`, `deps:`.

## 4. Status accounting

`git log`, the pull requests, the problem-report register, the traceability
matrix (`08-traceability/matrix.md`, regenerated in the pull request that
changes requirements, tests or tags; CI fails if the committed copy is stale, once OI-019 lands)
and the accomplishment summary (`11-summary/sas.md`).

## 5. Problem reports

Register: `10-configuration/problem-reports.md`. Classes: **S** safety-related
(can make a report wrong or misleading, or is a failure condition of the
hazard assessment), **F** functional, **P** process or documents, **C** change
request. States: Open, Analysed, Fixed (with the test), Verified, Closed (at a
release, with the tag). Security findings that should not be public before a
fix are handled privately first and entered when fixed.

## 6. Archive, retrieval and release

GitHub holds the repository; every clone is a full copy. Released engine
packages are on the package index, built from the tag by CI with Trusted
Publishing (no token in the repository). The service is deployed from `main`
after CI by `deploy.yml`. There is no separate off-site archive of baselines
and no procedure for rebuilding an old release bit for bit (open item
OI-008).

## 7. Environment control

Section 2 of `sdp.md`. A change of Python version, of a pinned tool or of a
CI action is a pull request like any other.
