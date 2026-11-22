# Review checklists

Used on every pull request, for whatever it touched. One person does the
review today, so they are self-checks (`docs/lifecycle/01-plans/sqap.md`).
Record the result in `review-records.md` beside this file when the change
touches a requirement, a threshold, a parser mapping, a golden result or a
plan: each item yes, no (with what was done about it) or n/a. Rule ids (RS-,
DS-, PY-, TS-) are in `docs/lifecycle/02-standards/`.

## System and safety

- [ ] A new function, input format, output, outside call or use of the report has been through the hazard assessment (`docs/lifecycle/04-safety/hazard-assessment.md`) before its requirements changed.
- [ ] New SYS requirements trace to an STK need or a SAF requirement and are allocated to items in `system-architecture.md`.
- [ ] An interface change is in its ICD (`docs/lifecycle/03-system/icd/`).
- [ ] The assumptions A1 to A5 of the hazard assessment still hold for what the change makes possible.

## Requirements

- [ ] Every new behaviour has an HLR and LLR with new ids and parents; ids are never reused (RS-02, RS-03).
- [ ] Each requirement is one testable statement. Numbers have units and limits (RS-06).
- [ ] A threshold that decides a severity is stated in an LLR with its number, unit and source (RS-18).
- [ ] Failure behaviour is stated: what is refused, skipped or warned about, and what the user sees (RS-08).
- [ ] Each `covers:` line names only requirements the test really exercises; each `Inspection` has an honest note (RS-05).
- [ ] `python tools/trace.py --check` passes and `matrix.md` is regenerated.

## Design

- [ ] The item's LLD is changed with the code.
- [ ] A unit conversion is done once, in the parser, with its factor in an LLR (DS-03).
- [ ] A check returns a skip, not a clean result, when it has nothing to check (DS-04).
- [ ] Anything skipped or guessed reaches `parse_warnings` (DS-08).
- [ ] No randomness, wall clock or ordering dependence in a rule (DS-07).
- [ ] A report schema change bumps `schema_version`, the exported schema and the changelog (DS-10).
- [ ] AI output can reach nothing but the summary text and the Q&A answer (DS-12).

## Code

- [ ] `ruff check flightmd_core api scripts tools tests` is clean; no new `noqa` without a code and a reason (PY-03).
- [ ] `npm run lint` and `npm run typecheck` are clean in `frontend/`; no new `any`, `@ts-ignore` or `eslint-disable` without a reason (TS-03).
- [ ] New code that implements an LLR carries its `@relation` tag.
- [ ] Outside input is checked once where it enters, with a size bound (PY-06).
- [ ] No secret, token or key is logged, printed, returned or committed.

## Tests

- [ ] A defect fix has a test that fails without the fix.
- [ ] A threshold is tested on both sides.
- [ ] Tests do not use the network, the wall clock or test order.
- [ ] `pytest -m "not integration and not corpus"`, `pytest -m integration` and `npm test` pass.

## Golden results (when a corpus result changes)

- [ ] Each changed finding was checked against the log in an independent viewer, not only against the old file.
- [ ] The reason for the change (which rule or parser change) is in the commit message.
- [ ] A finding that disappeared was confirmed not to be a real fault now missed.

## Parameter tables (when regenerated)

- [ ] The diff was read; the firmware version and the source of the metadata are in the pull request.
- [ ] Ranges that narrowed or widened were checked against the firmware's own documentation for a sample.

## Release

- [ ] CI is green on the tag; the corpus has run since the last parser or rule change.
- [ ] Problem reports classed S are closed or accepted in the release notes.
- [ ] `docs/lifecycle/README.md` and `11-summary/sas.md` match the tree.
