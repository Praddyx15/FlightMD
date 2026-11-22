# Lifecycle data

The index of FlightMD's lifecycle data: the items DO-278A asks of ground
software and the system and safety items of SAE ARP4754B and ARP4761A, the
file that holds each, and its state. Issue 1, 2026-11-22.

**Nothing here claims certification, approval, compliance or an agreed
assurance level.** FlightMD is ground software that analyses flight logs of
unmanned aircraft after the flight. DO-278A is used as a process frame by
choice, the ARP method by analogy; how well each fits is in
`01-plans/psaa.md`. Levels are proposals, to be agreed with the authority
concerned if there is ever one. References not checked against a standard's
text are marked "to confirm".

**The trace check passes on issue 1.** Every active HLR and LLR is either
named by a test or says why it is verified by review instead; every active LLR
is tagged in the code. The check runs in `pytest`, and so in CI (its own CI step is OI-019). What was run and
what is still open is in `07-verification/README.md`. Nothing has been
reviewed by a second person.

States: **exists** (there and current), **partial** (some of it; what is
missing is said), **planned** (not started).

## Folders

| Folder | Holds |
|---|---|
| `00-project-record/` | Decisions, open items, gap analysis |
| `01-plans/` | PSAA, SDP, SVP, SCMP, SQAP |
| `02-standards/` | Requirements standard and grammar, design standard, coding standards (Python, TypeScript) |
| `03-system/` | ConOps, stakeholder needs, system requirements, system architecture, ICDs (`icd/`) |
| `04-safety/` | Hazard assessment, FMEA, safety requirements |
| `05-requirements/` | Software high-level and low-level requirements, one `hlr-<item>.sdoc` and `llr-<item>.sdoc` per item |
| `06-design/` | High-level design and one `lld-<item>.md` per item |
| `07-verification/` | What tests exist, what was run, gaps |
| `08-traceability/` | StrictDoc config, how the trace works, the generated matrix |
| `09-reviews/` | Review checklists and records |
| `10-configuration/` | Problem reports |
| `11-summary/` | Accomplishment summary (draft) |

Kept where they were: the report schema and its changelog (`docs/schema/`),
the plugin guide (`docs/plugins.md`), the walkthrough, and the July 2026
50-log run (`verification/`, out of date).

## Software lifecycle data (DO-278A items; names as in DO-178C chapter 11, to confirm)

| Item | File | State |
|---|---|---|
| Plan for software aspects of approval | `01-plans/psaa.md` | Exists (agreed with nobody) |
| Software development plan | `01-plans/sdp.md` | Exists |
| Software verification plan | `01-plans/svp.md` | Exists |
| Software configuration management plan | `01-plans/scmp.md` | Exists |
| Software quality assurance plan | `01-plans/sqap.md` | Exists |
| Requirements standard | `02-standards/requirements-standard.md`, `requirements.sgra` | Exists |
| Design standard | `02-standards/design-standard.md` | Exists |
| Code standards | `02-standards/coding-standard-python.md`, `coding-standard-typescript.md` | Exists; ruff configuration and ESLint run clean; their CI steps wait for OI-019 |
| High-level requirements | `05-requirements/hlr-{int,prs,anl,dyn,rpt,api,web}.sdoc` | Exists for all seven items: 198 HLR (5 proposed). Not reviewed |
| Low-level requirements | `05-requirements/llr-{int,prs,anl,dyn,rpt,api,web}.sdoc` | Exists: 566 LLR (INT 72, PRS 90, ANL 94, DYN 65, RPT 66, API 116, WEB 63). Web pages and most components are at HLR level (D-10, OI-012). Not reviewed (OI-016) |
| Design description | `06-design/hld.md`, `lld-{int,prs,anl,dyn,rpt,api,web}.md` | Exists, as built |
| Source code | `flightmd_core/`, `api/`, `frontend/`, `scripts/` | Exists |
| Executable | Python package built by `publish.yml`; service image `api/Dockerfile`; web build | Exists |
| Verification cases and procedures | The tests (`07-verification/README.md`) | Exists: `covers:` lines on the tests of 60 files name the requirements they exercise |
| Verification results | CI runs; `07-verification/README.md` | Partial: the local runs of issue 1 are listed there; results are not archived per release (OI-008) |
| Environment configuration index | `01-plans/sdp.md` section 2; `pyproject.toml`, `api/requirements*.txt`, `frontend/package-lock.json` | Partial: no full lock for the engine |
| Configuration index | Git commit and tag (`01-plans/scmp.md`) | Exists |
| Problem reports | `10-configuration/problem-reports.md` | Exists: 48 reports; 8 fixed (2 in part) with regression tests, the rest open |
| Configuration management records | Git history, pull requests | Exists |
| Quality assurance records | `09-reviews/review-records.md` | Partial: the automated checks of issue 1 are recorded; no review by a second person |
| Accomplishment summary | `11-summary/sas.md` | Partial: draft |
| Trace data | `08-traceability/matrix.md` (by `tools/trace.py`); `@relation` tags in code; `covers:` lines in tests | Exists: 564 of 566 LLR tagged in code (the other 2 are procedures); 473 LLR and 171 HLR named by a test; the check passes |
| Tool qualification data | Stance per tool in `01-plans/psaa.md` section 6 | Planned: none claimed |

## System and safety data (ARP4754B, ARP4761A method)

| Item | File | State |
|---|---|---|
| Concept of operations, stakeholder needs | `03-system/conops.md`, `stakeholder-needs.sdoc` (12) | Exists; validated with nobody but the owner |
| System requirements | `03-system/system-requirements.sdoc` (39, of which 3 proposed) | Exists |
| System architecture and allocation | `03-system/system-architecture.md` | Exists |
| Interface control documents | `icd/icd-{log-formats,cli-library,report-and-exports,http-api,storage,web-ui,external-services}.md` | Exists, as built |
| Functional hazard assessment | `04-safety/hazard-assessment.md` (26 failure conditions) | Exists; not reviewed |
| FMEA | `04-safety/fmea.md` | Exists; not reviewed |
| Safety requirements | `04-safety/safety-requirements.sdoc` (15, of which 3 proposed) | Exists |
| Common-cause analysis, security assessment | - | Planned (OI-011) |
| Requirements validation records | `09-reviews/review-records.md` | Planned |

## Running the check

```bash
python tools/trace.py --check     # standard library only; writes 08-traceability/matrix.md
python tools/trace.py --html      # also StrictDoc HTML in .local/strictdoc (needs the dev requirements)
pytest tests/test_trace.py        # the same check inside the test suite
```
