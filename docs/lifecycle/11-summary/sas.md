# Accomplishment summary (draft)

FMD-SAS, draft 2, 2026-11-22. What exists, what is partial and what is open.
A draft: nothing has been reviewed by anyone but the author, no level has been
agreed, and nothing is certified or approved.

## 1. System and software

FlightMD analyses flight logs of unmanned aircraft after the flight and
reports a health score, findings with evidence, and parameter changes to
consider (`docs/lifecycle/03-system/conops.md`). Items: `intake`, `parsers`,
`analysers`, `report`, `api`, `web`, with `data` and `tools`. Package version
1.1.0 in `pyproject.toml` (the package itself states 1.0.0, PR-001); report
schema 1.7. Baseline documented: commit `50a1eba`.

## 2. Levels

Proposed, not agreed (`04-safety/hazard-assessment.md` section 5): AL5 for the
analysis chain, the service and the web application; AL6 for flight context.
The proposal rests on assumptions A1 to A5, which the product does not yet
show its users (PR-017). The recommendation path would be Major, not Minor,
if users load parameter files without review.

## 3. Lifecycle data: state

| Area | Exists | Partial | Open |
|---|---|---|---|
| Plans | PSAA, SDP, SVP, SCMP, SQAP | - | Not reviewed or agreed |
| Standards | Requirements, design, Python, TypeScript; ruff (E, W, F) in CI | Wider ruff run and ESLint in CI wait for OI-019 | No type checker for the engine (OI-009) |
| System | ConOps, 12 needs, 39 system requirements (3 proposed), architecture, 7 ICDs | - | Validation with stakeholders (OI-005) |
| Safety | Hazard assessment, FMEA, 15 safety requirements (3 proposed) | - | Review by a safety engineer; security assessment (OI-011) |
| Software requirements | 198 HLR and 566 LLR over seven items | Web pages and most components at HLR level (OI-012) | Review of all (OI-016) |
| Design | HLD, LLD for all seven items | - | Not reviewed |
| Code | All items built; tags in docstrings and comments; eight defects fixed with tests | - | 40 problem reports open |
| Verification | Tests name what they cover; trace check passes; full suite, web checks and StrictDoc export run (`07-verification/README.md`) | Structural coverage measured in CI, not analysed | Results not archived per release (OI-008) |
| Configuration | Git, pull requests, tags; problem-report register | - | Archive per release (OI-008) |
| Quality assurance | Plan and checklists | Automated checks recorded | No review by a second person; no independence (OI-003) |

## 4. Deviations from the plans

- The SDP's order (requirement, design, code, test) was not followed for the
  existing code: requirements were written from the code (decision D-03).
- 93 LLR and 30 HLR are verified by review only, each with a note; the
  matrix lists them as open (D-14).
- Fixes were made for the serious defects only (D-12); the rest are logged.

## 5. Open problem reports

40 of 48 open (PR-026 with a fix ready, OI-019), plus the open parts of PR-028 and PR-029. Safety-related and
still open, fully or in part: PR-001, 005, 007, 009, 017, 022, 028 (part), 029 (part), 031, 032, 037, 040,
042, 046. Register: `10-configuration/problem-reports.md`.

## 6. Statement

This record describes software and a process that are part-way documented.
It supports no claim of compliance with DO-278A or any other standard.
