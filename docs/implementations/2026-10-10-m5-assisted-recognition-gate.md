# M5 step 8: assisted cross-source recognition (TST-057A) and the M5 real-world gate

- **Date:** 2026-10-10
- **Milestone / tracker IDs:** M5 step 8; TST-057A, TST-057B (blocked), the M5 gate
- **Status:** evidence recorded; **awaiting the owner's manual confirmation and acceptance level** for TST-057A
- **Commits:** PR to be recorded when merged

## What was built

- `evaluation/assisted_recognition_gate.py`: a local script that starts the **real application** in-process (the real
  profile: installed `buffalo_l` SCRFD and ArcFace through the supervised worker, the measured abstain-only
  policy, a fresh library under `evaluation/datasets/gate-run`, which is Git-ignored) and drives it only through
  its HTTP API. Run it with
  `PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py --dataset evaluation/datasets/commons-pd
  --local-state-root local-models/state --workdir evaluation/datasets/gate-run --report
  evaluation/datasets/reports/gate.json --people 40 --minimum-photographs 5`.
  1. *Enrol*: each chosen person's photographs, except a held-out quarter, are imported (each a separate
     Source), processed, and each photograph's subject face (its only face, or one 2.5 times larger than the
     rest) is **placed** into that person's identity and the person named. This stands in for the human
     confirmation assisted recognition relies on; the application places nothing itself (automatic matching
     is off).
  2. *Query (TST-057A)*: each held-out photograph is searched with `POST /search/face`; the people offered are
     ranked by similarity; Recall@1, Recall@5 and MRR (with Wilson 95% intervals) are measured over people with
     at least two enrolled photographs.
  3. *Workflow*: name search; recycle (left out of default search, still in recognition memory) and restore;
     split then merge; permanent delete; forget (not recognised, still findable by name, labelled).
  4. *Restart*: the application is stopped and started again on the same library; the same queries give the
     same rankings; name search still works.
- `tests/unit/test_assisted_gate.py` (5) covers the script's selection and metric rules.
- Face search now looks at the nearest 50 faces (`SEARCH_SHORTLIST`) instead of the processing shortlist of 5,
  so several people can be ranked. With 5 the run measured Recall@1 = Recall@5 = MRR = 0.652 (the shortlist could
  hold one or two people, so rank depth was not measured); with 50: below. This is an agent decision
  recorded in the route.

## Result (this machine: Windows 11, Python 3.12.14, onnxruntime 1.30.0, CPU provider; report
`evaluation/datasets/reports/gate.json`, dataset manifest `9e111844...c555`)

**The identity labels are Commons categories and are not verified. They are not ground truth: a mislabelled
photograph can move every number below either way. The real-model recognition quality is therefore reported
as measured against provisional labels, not as verified.**

| Measure | Value |
|---|---|
| People chosen / photographs processed / runs failed | 40 / 495 / 0 |
| Enrolment photographs skipped (no face / no clear subject) | 82 / 244 |
| Eligible held-out queries (a clear subject, person has 2+ enrolled photographs) | 46 (105 held-out photographs left out) |
| Recall@1 | 0.717 (Wilson 95%: 0.575 to 0.827) |
| Recall@5 | 0.804 (0.668 to 0.893) |
| MRR | 0.754 |
| Queries wrote nothing | yes: sources, identities and runs counts equal before and after (495, 39, 495) |
| Workflow checks | 10 of 10 pass, including the restart |

Reading: the numbers are low for a recognition product and the set is small, formal, skewed to adult official
photographs and group shots (half of the enrolment photographs had no clear subject). They describe ranked
suggestions that a person confirms, which is what assisted recognition is.

## For the owner

- **TST-057A has no numeric acceptance level in the plan.** It says "validated with Recall@1, Recall@5 and MRR plus
  manual confirmation". I therefore recorded the evidence and left the row `IN_PROGRESS`. Please decide the
  level you accept (or that the numbers above are enough) and do the manual confirmation (run the script, or try
  the Search screen with your own photographs), then I will mark it `PASSING`.
- **TST-057B stays `BLOCKED pending calibration`**; nothing here changes it.
- The run used the CPU. A CUDA run and a larger, verified set (R5) are the next honest improvements.
