# Open items

Items that need a decision, a fact not yet confirmed, or work not yet
scheduled. Ids are never reused; closed items stay with how they closed.

| Id | Item | Why it matters | Next action | Status |
|---|---|---|---|---|
| OI-001 | Assurance levels and the assumptions A1 to A5 are proposals nobody has agreed | Every level in `psaa.md` rests on them | Review the hazard assessment with someone who has done one; agree only if an authority is ever involved | Open |
| OI-002 | Which rules an operator using the tool is actually held to (UAS regulation, maintenance instructions, ASTM F3201 to confirm) | DO-278A is a chosen frame, not an obligation | Read the applicable rules for one target operator type | Open |
| OI-003 | Independence: one person writes code, requirements, tests and reviews | No verification or QA objective is met with independence | Find a second reader for threshold changes and golden results first | Open |
| OI-004 | Limits of use are not shown to users (SAF-015, SYS-026; PR-017) | The Minor classification assumes users know them | Decide the wording; add to web, PDF and exports with tests | Open |
| OI-005 | Stakeholder needs and the ConOps are validated with nobody but the owner | Requirements may answer the wrong need | Ask two users of each kind (pilot, tuner, integrator) | Open |
| OI-006 | Data quality of the parameter tables, safe ranges and thresholds: no recorded source per value, no retrieval date or source hash in a table, no check against upstream | A wrong range gives wrong parameter findings (FC-6.3) | Record source and date in the generator output; list threshold sources in the LLD tables | Open |
| OI-007 | No assurance argument for third-party decoders and numeric libraries beyond tests and the corpus | Every result depends on them | Keep pins exact for the engine as for the service; note decoder versions in the report | Open |
| OI-008 | No archive of baselines or test results per release; no rebuild procedure | A past report cannot be reproduced with certainty | Keep CI results and the lock file with each tag | Open |
| OI-009 | No type checker | Unit and `None` mistakes that a checker would find | Try mypy or pyright on `flightmd_core`; list what fails | Open |
| OI-010 | `zip` without `strict=` in 16 places (PY-D9) | A silent tail drop where the series are data | Review each | Open |
| OI-011 | No security assessment or threat model | Uploads are untrusted; airframe tokens, webhooks and the pickle cache are attack surfaces | Write one; the API's LLR are its input | Open |
| OI-012 | Web application pages and components have HLR only | No LLR, tags or unit tests for most of what the user sees | Second pass over `frontend/app` and `frontend/components` | Open |
| OI-013 | Test tags (`covers:` lines) are missing for most requirements, so the trace check fails | The check is hooked into `pytest` and CI and will fail both until the tags are in | Owner to confirm that comment lines may be added to test files; then tag, regenerate the matrix | Closed 2026-11-22: owner agreed (D-13); tags added; the check passes |
| OI-014 | Frontend checks (`npm run lint`, `tsc`, Vitest) were not run for issue 1 | TS-D6, PR-026 | Owner to confirm a local install; run; add lint to CI if clean | Closed 2026-11-22: `npm ci`, lint, `tsc` and Vitest run (results in `07-verification/README.md`); lint added to CI |
| OI-015 | The corpus has real logs for PX4 and ArduPilot only | Betaflight, INAV, DJI and text dataflash results rest on built logs (FC-2.1) | Find public logs with a licence that allows use | Open |
| OI-016 | The LLR were written from the code in one pass and not read against it by a second person | An LLR may misstate the code | Review per item with the checklist | Open |
| OI-017 | Vitest fails on Node 26 unless `NODE_OPTIONS=--no-experimental-webstorage` is set: Node's own `localStorage` hides the test DOM's | A developer on a current Node sees 56 failures that are not real | Pin the Node version for development (`.nvmrc` or `engines`) or set the option in the test script | Open |
| OI-018 | The API LLR record defects in their COMMENT fields; the register holds them as PR-043 to PR-049 | - | Fix in order of class S first (PR-046, PR-042, PR-040) | Open |
