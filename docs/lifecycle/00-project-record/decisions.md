# Decisions

Project-level decisions that shape the lifecycle. "Owner" is the repository
owner; "Issue 1" is the work that set this folder up.

| Id | Date | Decision | By | Where it shows |
|---|---|---|---|---|
| D-01 | 2026-11-19 | Frame: FlightMD is ground software. DO-178C does not apply. DO-278A is used as the process frame by choice; the ARP4754B and ARP4761A method is used at system and safety level by analogy; DO-200B data-quality ideas by analogy for the data a result depends on. Applicability of each is "to confirm" | Owner | `01-plans/psaa.md` section 2 |
| D-02 | 2026-11-19 | Never claim certification, approval or a granted level. Levels are proposals "to be agreed with the authority"; uncertain references are marked "to confirm" | Owner | `psaa.md`, `04-safety/hazard-assessment.md`, `README.md` |
| D-03 | 2026-11-19 | "Process and as-built": document the code as it is, put the process in place, no rewrites. Fix only serious defects, each with a test | Owner | `05-requirements/`, `06-design/`, `10-configuration/problem-reports.md` |
| D-04 | 2026-11-19 | Configuration management is git and GitHub as the repository already uses them: pull requests to `main`, CI before merge, release by tag | Owner | `01-plans/scmp.md` |
| D-05 | 2026-11-20 | Requirements in StrictDoc at five levels (STK, SAF, SYS, HLR, LLR), one HLR and one LLR document per software item; ids `HLR-<ITEM>-nnn`, `LLR-<ITEM>-nnn` | Issue 1 | `02-standards/requirements-standard.md` |
| D-06 | 2026-11-20 | The trace check is a standard-library script that reads the `.sdoc` files itself; StrictDoc is for authoring and browsing. The check runs in `pytest` and as a CI step, and CI fails on a stale committed matrix | Issue 1 | `tools/trace.py`, `tests/test_trace.py`, `08-traceability/README.md` |
| D-07 | 2026-11-20 | A requirement with no test is not hidden: it says `Inspection` with a note and the matrix lists it as open. The check allows that for HLR as well as LLR | Issue 1 | Requirements standard RS-05 |
| D-08 | 2026-11-20 | Code tags: function docstrings in Python, file scope for pydantic models, FastAPI route handlers and TypeScript, so that a tag never changes the published schema, the OpenAPI text or behaviour | Issue 1 | Requirements standard section 6 |
| D-09 | 2026-11-20 | Coding standard enforcement with the repository's own linters only (ruff, ESLint, `tsc`). ruff rule sets were widened to what the code already met; everything else is a listed deviation; no code changed for a rule. No type checker added | Issue 1 | `02-standards/coding-standard-python.md`, `pyproject.toml` |
| D-10 | 2026-11-20 | Web application: LLR for `frontend/lib` and the tested components first; pages and other components at HLR level in this issue | Issue 1 | `06-design/lld-web.md`; open item OI-012 |
| D-11 | 2026-11-20 | No defect is fixed in issue 1. Each fix needs a failing test first, and changes to test files were held back pending the owner's answer (OI-013) | Owner, Issue 1 | `10-configuration/problem-reports.md` |
| D-12 | 2026-11-22 | Supersedes D-11 for the reports it names: the serious defects PR-002, PR-003, PR-004, PR-018 and PR-027 to PR-030 are fixed in issue 1, each with a regression test that fails on the old code; the others stay logged | Owner | `10-configuration/problem-reports.md` |
| D-13 | 2026-11-22 | `covers:` comment lines may be added above existing tests, and `@relation` tags in docstrings and comments, without other changes to the tests or code (closes OI-013). A `covers:` line on a test of an LLR also names that LLR's parent HLR | Owner, Issue 1 | Tests; requirements standard section 6 |
| D-14 | 2026-11-22 | A requirement whose behaviour no test checks directly says `Inspection` with a note naming what a review reads, rather than claiming a test that only passes through the code | Issue 1 | RS-05; `08-traceability/matrix.md`, section Open |
