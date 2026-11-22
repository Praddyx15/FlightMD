# Verification: what exists, what was run, what is missing

FMD-VER, issue 1, 2026-11-22. The plan is `docs/lifecycle/01-plans/svp.md`.
This file is the state.

## 1. Tests in the repository

| Tier | Where | Size | Runs |
|---|---|---|---|
| Unit tests, engine and service | `tests/test_*.py` (pytest) | About 820 test functions in 49 files | CI, every push and pull request, Python 3.11 to 3.13 |
| Integration on sample logs | `tests/test_sample_logs.py`, marker `integration`; 8 sample logs in `tests/sample_logs/` | 24 test functions | By hand (`pytest -m integration`); not in CI |
| Real-log corpus | `tests/corpus/`, marker `corpus`; 17 public logs named in `manifest.json` with URL and SHA-256 | 2 test functions over 17 logs | Weekly in CI (`corpus.yml`) and on demand |
| Web unit tests | `frontend/test/*.test.ts(x)` (Vitest) | 69 cases in 10 files | CI |
| End-to-end smoke | `frontend/e2e/smoke.spec.ts` (Playwright) | 1 | CI, against a started API and web application |
| Schema | `tests/test_schema.py` | 4 | CI |
| Trace check | `tests/test_trace.py`, `tools/trace.py --check` | 4 | CI (added in this issue; passes, section 3) |

Static checks in CI: ruff (rule sets in `pyproject.toml`), `tsc --noEmit`,
`pip-audit`, a bundle-size budget, and since this issue ESLint (`npm run lint`).

## 2. What was run for issue 1

Run on 2026-11-22 on the branch of this issue, on one Windows machine (Python
3.12 in a virtual environment, Node 26), after the last code change.

| Check | Result |
|---|---|
| `pytest` (whole suite, default markers; includes `tests/test_trace.py`) | 1053 passed, 26 skipped (corpus logs not downloaded and tests that need optional system libraries) |
| `ruff check` with the configuration in `pyproject.toml` | No findings |
| `python tools/trace.py --check` | No problems |
| `python tools/trace.py --html` (StrictDoc 0.31.0 export of every `.sdoc` file) | Completed; StrictDoc reported no grammar or parse error |
| `npm ci` in `frontend/` | Completed |
| `npm run lint` | No warnings or errors |
| `npm run typecheck` (`tsc --noEmit`) | No errors |
| `npm test` (Vitest) | 84 of 84 passed with `NODE_OPTIONS=--no-experimental-webstorage`; without it 56 fail on Node 26 because Node's own `localStorage` hides the test DOM's (OI-017). CI uses Node 20 |

Not run locally: the Playwright smoke test, the integration marker
(`pytest -m integration`), the corpus (`pytest -m corpus`), the web build and
the bundle budget. CI runs them on the pull request.

Each fixed problem report has a regression test that failed on the old code;
for PR-003 the failure on the old code was checked by running the new test
against it (`zlib.error`, `KeyError`). The register names each test.

## 3. Trace check: state

`matrix.md` is regenerated and current. The check reports no problems:

| Level | Active | Named by a test | Review or analysis only, with a note |
|---|---|---|---|
| HLR | 193 | 171 | 30 (some say Test and Inspection) |
| LLR | 566 | 473 | 93 |

564 of 566 active LLR are tagged in the code; the other two are procedures.
`covers:` lines are in 60 test files (Python and TypeScript). A `covers:` line
on a test of an LLR also names the LLR's parent HLR (D-13). Where a test only
passes through code without checking the statement, the requirement says
`Inspection` with a note on what a review reads (D-14).

## 4. Requirements coverage

The `covers:` lines were added to existing tests by reading their names and
bodies against the requirement titles and statements, in one pass, by the
author of the requirements. They have not been checked by a second person
(OI-003, OI-016): a test may name a requirement it exercises only in part.
The requirements verified by review only are listed under "Open" in the
matrix with the reason.

## 5. Structural coverage

CI measures line coverage of `flightmd_core` and `api` with `pytest-cov` and
uploads the XML. No figure was taken for this issue, no threshold is
enforced, and uncovered code is not analysed. Branch coverage and the web
application's coverage are not measured.

## 6. Gaps

- Real logs for PX4 and ArduPilot only: 13 ULog, 2 dataflash, 2 telemetry
  logs. No text dataflash, Betaflight, INAV or DJI log in the corpus (OI-015).
- The corpus comparison is loose and can pass having compared nothing
  (PR-016); no review of the golden files is recorded.
- The integration tier is not in CI.
- The false-clean cases of PR-027 to PR-030 now have tests; the other checks have not been
  searched for the same pattern (FMEA AN-02).
- No test of determinism as such (two runs compared field by field).
- No test that checks running in threads do not alter shared tables (FMEA
  IN-08).
- The 50-log run in `verification/` describes the July 2026 engine and is out
  of date.
- No independence (OI-003); no kept results per release (OI-008).
