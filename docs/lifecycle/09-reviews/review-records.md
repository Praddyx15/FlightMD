# Review records

One row per review done with `review-checklists.md`. A review by the author
of the change is recorded as a self-check.

| Date | What | Checklist sections | Reviewer | Result |
|---|---|---|---|---|
| - | - | - | - | No review against the checklists has been recorded yet |

Issue 1 of the lifecycle data (2026-11-20 to 2026-11-22) has not been through
the checklists, by its author or anyone else. The automated checks that were
run on it, with their results, are in `07-verification/README.md` section 2:
the whole Python test suite, ruff, the trace check, the StrictDoc export, and
the web application's lint, type check and unit tests. Those runs show that the
documents, tags and tests agree with each other; they are not a review of
whether the requirements are right.

No golden-result review is recorded for the files in `tests/corpus/golden/`
(problem report PR-016); the next change to one starts the record.
