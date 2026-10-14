# The celebrity set from Commons: reviewed, exported, gate started

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`: 36 of the 40 identities)
- **Status:** the verified manifest is exported; **the gate run on it was started and its result is not
  recorded here** (see Next); no threshold, policy or model changed
- **Commits:** PR to be recorded when merged

## What was done

- `evaluation/collect_commons_portraits.py` (PR 193) collected 536 pictures for 36 people into
  `evaluation/datasets/celebs-commons/` (free Creative Commons and public-domain files read from
  Wikimedia Commons; `identity_verified: false`, `rights_reviewed: false` per record).
- **The owner reviewed the set** and marked 12 photographs EXCLUDED and 8 UNCERTAIN; the owner stated
  that every other photograph was checked and verified (2026-10-14).
- **How that was recorded.** The review tool stores a decision only when one is made, so the unmarked
  516 photographs were *unreviewed* in its log. The agent recorded 516 `VERIFIED` decisions through
  `Review.decide`, reviewer `sodiq`, each with the note "bulk-recorded 2026-10-14 by the agent from the
  owner's statement". The log therefore distinguishes them from click-by-click decisions, and the
  claim of verification is the owner's statement, not an individual check by the agent.
- **Export:** `evaluation/datasets/celebs-commons/review/exports/verified-20261014T223246658800Z.json`:
  516 verified photographs, 36 identities (all with at least 6 verified photographs), 106 held-out
  queries; against the owner's targets (40 identities, 80 queries) the **shortfall is 4 identities**,
  none for queries.
- **The gate was started** on that manifest with 28 enrolled and 8 never-enrolled people:

```bash
PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py \
  --dataset evaluation/datasets/celebs-commons \
  --manifest evaluation/datasets/celebs-commons/review/exports/verified-20261014T223246658800Z.json \
  --local-state-root local-models/state --workdir evaluation/datasets/gate-celebs-commons \
  --report evaluation/datasets/reports/gate-celebs-commons.json \
  --people 28 --unknown 8 --minimum-photographs 5 --run-timeout 3600
```

  (about 30 to 40 minutes on CPU; the report is first written *partial* after the queries and replaced
  when the workflow and restart phases finish).
- The five gate working folders from earlier runs (about 1.1 GB) and `celebrities-cc` (251 pictures from
  the first, noisy download) were deleted at the owner's request; the report files are kept.

## Limits to carry into any claim

- The labels are Commons categories checked by one reviewer. The set is celebrity photographs (many
  likely in the recogniser's training data: a possibility, not measured) and only pictures where
  SCRFD found one dominant face, so it cannot show detector recall or unfiltered performance.
- 36 identities are below the owner's 40.
- Rights are unreviewed (`rights_reviewed: false`); files stay local and are never redistributed.

## Next

See `.agents/CONTEXT.md`, "Next steps (2026-10-15)".
