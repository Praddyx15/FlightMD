# Software verification plan

FMD-SVP, issue 1, 2026-11-20. How FlightMD is verified. What exists today and
its gaps are in `docs/lifecycle/07-verification/README.md`.

## 1. Methods

| Method | Used for | Where |
|---|---|---|
| Requirements-based unit tests | LLR and HLR of the engine and the service | `tests/test_*.py` (pytest); each test names what it covers |
| Integration tests on sample logs | The pipeline end to end on small logs of each format kept in the repository | `pytest -m integration`, `tests/sample_logs/` |
| Real-log regression corpus | Results on real public logs against reviewed expected results | `pytest -m corpus`, `tests/corpus/`; weekly in CI and before a release |
| Web unit tests | `frontend/lib` and tested components | Vitest, `frontend/test/` |
| End-to-end smoke test | Upload to report through the real API and web application | Playwright, `frontend/e2e/smoke.spec.ts` |
| Schema check | Published schema equals the model | `tests/test_schema.py` |
| Trace check | Requirements, tests and code tags agree | `tools/trace.py --check`, `tests/test_trace.py` |
| Static analysis | Coding standards | ruff; ESLint; `tsc --noEmit` |
| Dependency audit | Known vulnerabilities | `pip-audit` |
| Review (inspection) | Requirements, design, code, and every requirement marked Inspection | Pull request, `09-reviews/review-checklists.md` |
| Analysis | Hazard assessment, FMEA; determinism argument | `04-safety/` |

## 2. What a test must do

- Name the requirements it covers on the line above it
  (`# covers: HLR-..., LLR-...`).
- Check the behaviour the requirement states: normal range, the threshold on
  both sides where one decides a severity, and the error or skip case.
- Not depend on the network, the wall clock or test order. CI runs with
  `FLIGHTMD_OFFLINE=1` and empty AI keys.
- Use built logs (the writers in `tests/`) or the sample logs; real logs
  belong to the corpus.

## 3. The corpus and its expected results

Real logs find what built logs cannot: a field the parser maps wrongly, a
threshold that fires on every healthy flight. The corpus manifest names each
log and where it is fetched from. Expected results (`tests/corpus/golden/`)
are written by `pytest -m corpus --update-golden`, **read by a person** and
committed only when agreed. A changed result fails the weekly run until the
new result is reviewed (safety requirement SAF-014). Reviewing a golden file
means checking each finding against the log in an independent viewer, not
only against the previous file. Records of those reviews are kept in
`09-reviews/review-records.md`.

## 4. Coverage

- **Requirements coverage**: the matrix (`08-traceability/matrix.md`). Every
  active HLR and LLR is either named by a test or listed as verified by
  inspection with the reason. The aim is to turn inspection-only rows that
  decide a finding into tests first.
- **Structural coverage**: CI measures line coverage of `flightmd_core` and
  `api` with `pytest-cov` and keeps the XML as a build artifact. No threshold
  is enforced and no analysis of uncovered code is done yet. Decision and
  branch coverage are not measured. The web application's coverage is not
  measured.

## 5. Independence

One developer writes the code, the requirements and the tests. Independence
is not met for any objective (open item OI-003). Partial substitutes in
place: the corpus compares against real logs the developer did not make; the
autopilots' own health figures (vibration metrics, EKF test ratios) are used
before FlightMD's own computations where the log has them.

## 6. Environment

Tests run on Linux in CI (Python 3.11, 3.12, 3.13; Node 20) and on the
developer's machine. PDF tests need Pango from the operating system and are
skipped where it is missing. The deployed service is checked by the smoke
step of `deploy.yml` (API health and the front page), nothing more.

## 7. Results

CI logs and artifacts (coverage XML, Playwright report on failure) are the
record, kept by GitHub for its retention period. Results are not archived per
release (open item OI-008). The 50-log run in `verification/` is a record of
the July 2026 engine and is out of date for the current rules; it is kept for
history only.

## 8. Regression

Every pull request runs everything in section 1 except the corpus and the
integration marker. A defect fix comes with a test that fails without it.
