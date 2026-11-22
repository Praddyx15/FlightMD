# Software development plan

FMD-SDP, issue 1, 2026-11-20. How FlightMD is developed, as it is actually
done in this repository, with the steps this lifecycle adds.

## 1. Life cycle

Changes are small and continuous. One change goes through:

1. **Need.** An issue, a finding from a real log, or a problem report
   (`docs/lifecycle/10-configuration/problem-reports.md`).
2. **Requirement.** New behaviour gets or changes an HLR and its LLR in
   `docs/lifecycle/05-requirements/` before or with the code. A new function,
   input format, output or outside call first goes through the hazard
   assessment (`04-safety/hazard-assessment.md`) and, if it adds an
   interface, its ICD.
3. **Design.** The item's `06-design/lld-<item>.md` is changed with the code.
4. **Code.** To the coding standards in `02-standards/`; the code carries
   `@relation(LLR-...)` tags.
5. **Test.** Requirements-based tests name what they cover (`covers:`).
6. **Check.** `pytest` locally (it includes the trace check), then CI.
7. **Review and merge.** Pull request from `dev` (or a topic branch) to
   `main`, with the checklist of `09-reviews/review-checklists.md`.
8. **Release.** A `vX.Y.Z` tag publishes the engine; `main` deploys the
   service (`scmp.md`).

The existing code predates steps 2, 3 and the tags. Its requirements and
design were written from the code in November 2026 (decision D-03); from now
on the order above holds.

## 2. Environment

| Thing | Version | Where it is fixed |
|---|---|---|
| Python | 3.11 to 3.13 (CI runs all three); the service image and deploy use 3.11 | `pyproject.toml`, `.github/workflows/ci.yml`, `api/Dockerfile` |
| Engine dependencies | pyulog, pymavlink, numpy, scipy, pandas, pydantic (lower bounds) | `pyproject.toml` |
| Service dependencies | Exact pins for direct dependencies, ranges for the numeric stack | `api/requirements.txt`; full lock by the `Lock API requirements` workflow when run |
| Development tools | pytest 8.3.4, pytest-asyncio, pytest-cov, httpx, ruff 0.8.4, pip-audit, pip-tools, StrictDoc 0.31.0 | `api/requirements-dev.txt` |
| Node | 20 in CI | `.github/workflows/ci.yml` |
| Web dependencies | Next.js 14.2, React 18, TypeScript 5, ESLint 8, Vitest 2, Playwright | `frontend/package.json`, `frontend/package-lock.json` |
| CI actions | Pinned to commit SHAs | `.github/workflows/*.yml` |

A local environment is a virtual environment in the repository folder
(`.venv/`, ignored by git) and `frontend/node_modules/` (ignored).

## 3. Standards

Requirements: `02-standards/requirements-standard.md`. Design:
`02-standards/design-standard.md`. Code: `02-standards/coding-standard-python.md`
and `coding-standard-typescript.md`.

## 4. Languages and what is not used

Python for the engine, the service and the tools; TypeScript (React) for the
web application; JSON for shipped data; Jinja2 HTML for the PDF templates. No
generated code is committed except `frontend/app/tokens.css` (from
`frontend/design/tokens.json`, ignored by ESLint) and the parameter tables
(from firmware metadata, `psaa.md` section 5).

## 5. Third-party software

Everything the result depends on that this project did not write: the
decoders (`pyulog` for ULog, `pymavlink` for dataflash and MAVLink), the
numeric stack (numpy, scipy, pandas), pydantic, and for the service FastAPI,
uvicorn and WeasyPrint. The Betaflight and DJI decoders are this project's own
code. The dependencies are identified by version (section 2) and audited for
known vulnerabilities by `pip-audit` in CI. No assurance argument beyond their
tests and the corpus results is made for them (open item OI-007).

## 6. Transition criteria

| To | Needs |
|---|---|
| Merge to `main` | CI green: unit tests on three Python versions, trace check, ruff, dependency audit, frontend type check, ESLint (once OI-019 lands), unit tests, build and bundle budget, Playwright smoke test; review checklist done |
| Release tag | CI green on the tag; the tag matches the package version (checked by `publish.yml`); corpus run green since the last parser or rule change; problem reports classed S (safety-related) closed or accepted in writing in the release notes |
