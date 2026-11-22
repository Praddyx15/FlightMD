# Lifecycle gap analysis

FMD-GAP, issue 1, 2026-11-20. What the repository held before this work
against what a DO-278A-style record asks for, and what it holds after.
Baseline examined: commit `50a1eba` on `main`. Index of every item:
`docs/lifecycle/README.md`. Nothing here claims compliance.

## 1. What kind of software this is

Ground software that analyses flight logs of unmanned aircraft after the
flight: a Python engine (about 8,400 lines), a FastAPI service (2,500) and a
Next.js web application (5,600), with about 820 Python test functions and 70
web tests. Nothing runs on an aircraft. Frame chosen: DO-278A as the process
frame, ARP4754B and ARP4761A method by analogy, DO-200B data-quality ideas by
analogy (`01-plans/psaa.md` section 2).

## 2. Before and after

| Area | Before | After issue 1 |
|---|---|---|
| Plans | None. README sections on tests and deploying | PSAA, SDP, SVP, SCMP, SQAP, written to how the repository works |
| Standards | ruff with E, W, F in CI; ESLint and `tsc` configured | Requirements, design, Python and TypeScript standards; ruff widened to 14 rule sets with listed deviations |
| System level | README feature list; walkthrough | ConOps, 12 needs, 39 system requirements, architecture with allocation; 7 ICDs |
| Safety | None | Hazard assessment (26 failure conditions, levels proposed), FMEA, 15 safety requirements |
| Software requirements | None written. Behaviour stated only in the README, docstrings and tests | 198 HLR and 566 LLR for all seven items (web pages and most components at HLR level) |
| Design | Module docstrings; `docs/plugins.md`; report schema | HLD; LLD for all 7 items |
| Code to requirement trace | None | `@relation` tags for 564 of 566 LLR (the other 2 are procedures) |
| Test to requirement trace | None | `covers:` lines in 60 test files: 473 LLR and 171 HLR named by a test |
| Trace tool | None | `tools/trace.py`, hooked into `pytest` and CI; passes |
| Verification | Good test base, CI on three Python versions, weekly real-log corpus, schema test, dependency audit | Described; gaps listed; regression tests for the fixed defects; full suite, web checks and StrictDoc export run on this branch |
| Configuration management | Git, pull requests, pinned CI actions, release by tag | Unchanged, now written down; problem-report register started |
| Problem reports | GitHub issues only | 48 reports from reading the code; 8 fixed (2 in part), each with a regression test; 1 closed by a CI change |
| Reviews, QA | None recorded | Checklists; no review recorded |
| Summary | None | Draft |

## 3. What the work found

Writing requirements from the code surfaced defects that tests had not (those
fixed in issue 1 are marked in the register): four
checks that can report a clean 100 with no usable data (PR-027 to PR-030), a
score clamp that may turn NaN into 100 (PR-002), a PDF that says "no
significant issues" when nothing was assessed (PR-004), zero-filled positions
and altitudes (PR-007), an unbounded parameter suggestion (PR-031), and a
report that does not carry the engine version (PR-001). The full list is
`10-configuration/problem-reports.md`.

## 4. Still open, in order

1. Fix the open safety-related problem reports, each with a test: PR-001,
   005, 007, 009, 017, 022, 031, 032, 037, 040, 042, 046, and the open parts of
   PR-028 and PR-029.
2. A second reader for the hazard assessment and the LLR (OI-001, OI-003,
   OI-016).
3. LLR for the web pages and the untested components (OI-012).
4. Security assessment (OI-011); results kept per release (OI-008).
