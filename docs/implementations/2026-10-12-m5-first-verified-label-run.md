# M5: first run on human-verified labels (TST-057B evidence, not a pass)

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** M5 R5 follow-up; TST-057B (stays `BLOCKED`)
- **Status:** evidence recorded; TST-057B is **not** claimed
- **Commits:** PR to be recorded when merged

## What was run

The owner reviewed 292 of the 662 photographs with `evaluation/label_review.py` (205 VERIFIED, 66 UNCERTAIN,
21 EXCLUDED, none marked INCORRECT; 90 of the verified ones were flagged and so left out). The export
`review/exports/verified-20261012T103807344262Z.json` holds 115 photographs of 27 identities, of which 9 identities
have 5 or more photographs. `evaluation/assisted_recognition_gate.py --manifest <that export>` was run on the real
`buffalo_l` runtime (CPU); report `evaluation/datasets/reports/gate-verified.json`.

## Result

| Measure | Value |
|---|---|
| Identities / photographs enrolled / held-out queries | 9 / 61 / 18 |
| Recall@1, Recall@5, MRR | 1.000 / 1.000 / 1.000 (Wilson 95% interval, for the two recalls only: 0.824 to 1.000; none is computed for MRR) |
| Workflow checks (name search, recycle, restore, split, merge, delete, forget, restart) | 10 of 10 |
| Ranking stability after restart | same rankings |
| Queries wrote nothing (sources, identities, runs unchanged) | yes (61, 9, 61); this check compares counts only |

## What this does and does not show

- **It meets the provisional numeric thresholds** (Recall@1 >= 0.85, Recall@5 >= 0.95, MRR >= 0.90) on this set,
  and it is consistent with the earlier suspicion that most of the 0.739 on unverified labels was label noise
  and group photographs, not the model.
- **It does not pass TST-057B**, for three reasons: (1) the verified set is far below the dataset targets: 9 of 40
  identities with 5+ photographs, 18 of 80 held-out queries, only 7 of 9 identities have 2 or more queries;
  (2) **selection bias**: the owner verified only photographs they could confidently identify, so the hard cases
  (66 UNCERTAIN, 90 flagged, 370 unreviewed) are exactly the ones left out, and a perfect score on the easy ones
  says little about the rest; (3) **the open-set evaluation was not built at that time** (it is now: see [the open-set entry](2026-10-12-m5-open-set-evaluation.md)): nothing here measures what happens
  to a person who is *not* enrolled (false matches and abstentions), which TST-057B requires and which closed-set
  retrieval cannot show.
- 18 queries is too few for any claim beyond "no failures were seen"; the interval's lower bound is 0.824.

## Next

1. Build the open-set evaluation (people held out of enrolment entirely, reported apart from closed-set).
2. Report per-identity retrieval and keep this run as the verified-label baseline.
3. The owner continues the review (370 photographs are untouched) or accepts a justified expansion of the pool;
   the dataset targets are not to be met by forcing labels.
