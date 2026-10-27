# Corpus goldens

One `<id>.json` per log in `../manifest.json`: what FlightMD should say about that real
flight. They are empty on purpose. Nobody has run the corpus yet, and a golden written
without a person reading the log first only pins down whatever the code does today.

## First run

```
pip install -e ".[dev]"
FLIGHTMD_CORPUS_DIR=tests/corpus/logs pytest -m corpus --update-golden
```

This downloads the 17 logs (about 170 MB, kept out of git by `tests/corpus/.gitignore`),
checks each against its sha256, runs the full analysis offline and writes the goldens.

Then review every file before committing it. For each log, open it in Flight Review
(the `source` link in the manifest) or Mission Planner / UAV Log Viewer and check:

- `findings`: each `kind|severity` is something you can see in the log. Delete the
  golden, fix the analyser, and regenerate if one is wrong; don't edit a wrong
  finding into the golden.
- `assessed_modules`: a module missing here should be missing for a reason (no ESC
  data, no EKF topic...).
- `metrics`: spot-check two or three against the plots.
- `metadata`: vehicle type, airframe and firmware match the manifest.

Commit the goldens together with a note of what you checked.

## Later runs

`pytest -m corpus` compares against the goldens: the score has to stay inside
`score_band` (+-5 by default), the set of findings and assessed modules has to match
exactly, and each metric has to be within 10 % (or 0.05 absolute). Widen a single
metric with a `tolerances` block, e.g.

```json
"tolerances": {"vibration.max_rms": {"rel": 0.2}}
```

When a change moves a result on purpose, rerun with `--update-golden` and review the
diff like any other code change. Missing goldens and logs that can't be downloaded
skip; a log whose sha256 no longer matches fails, because the URL now serves a
different file.
