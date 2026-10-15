# The celebrity set from Commons: reviewed, exported and gated

- **Date:** 2026-10-14
- **Milestone / tracker IDs:** M5 track R; TST-057B (stays `BLOCKED`: 36 of the 40 identities)
- **Status:** the verified manifest is exported and the gate run on it finished (2026-10-14 23:50):
  retrieval, stability and workflow figures meet the owner's thresholds, but **TST-057B is not passed**
  (36 of 40 identities); no threshold, policy or model changed
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

## Result (final report, finished 2026-10-14 23:50; first read from the partial report at 23:43)

| Measure | Value |
|---|---|
| Enrolled people / photographs placed | 28 / 323 (none lost) |
| Held-out queries evaluated | 84 |
| Recall@1, Recall@5, MRR | 0.988, 0.988, 0.988 (Wilson 95% for the recalls: 0.936 to 0.998) |
| Stranger queries / accepted by the real policy | 109 / 0 |
| Best stranger similarity | 0.309 |
| Cut-off read-out | 0.30: 3 strangers accepted; 0.35 to 0.55: 0 accepted, known accepted correctly 97.6% at 0.35 and 0.40, 96.4% at 0.45, 90.5% at 0.50, 86.9% at 0.55 |
| Library counts unchanged by the queries | yes: 323 sources, 28 identities, 323 runs before and after (counts only) |
| Workflow checks | 10 of 10 (name search, recycle and restore, split then merge, permanent delete, forget, restart name search, same rankings) |
| Same rankings after a restart | yes (the 84 rankings after the workflow equal those after the restart) |
| Recall@1 after the workflow and restart | 0.952 (80 of 84): the 3 queries of the person the workflow forgets (Scarlett Johansson) no longer match, by design, plus the miss below |

The one miss: Morgan Freeman `015.jpg`, whose own identity is not among the offered candidates (top
candidate Tom Hanks at 0.145, so the real policy would abstain rather than answer wrongly).

Against the owner's thresholds (Recall@1 0.85, Recall@5 0.95, MRR 0.90, stability 100%, workflow
100%) **every measured figure passes**. "Zero unintended mutations" is only partly measured: the gate
compares the source, identity and run counts before and after the queries, which cannot see row
updates, other tables or file writes, so full non-mutation is not established by this run. Still,
 but the set has **36 identities
of the required 40** (28 of them enrolled in this run), so **TST-057B is not passed** and stays
`BLOCKED`; automatic acceptance stays off. These strangers are random other celebrities, not
look-alikes (issue 177), and the sample is small (Wilson 95% interval for 0 of 109: 0 to 0.034 if
queries were independent, which they are not).

## Closing the identity gap (2026-10-15)

`collect_commons_portraits.py --out evaluation/datasets/celebs-commons --licence free --per-person 15
--people-file evaluation/datasets/celebs-commons/people-2026-10-15.txt` (the collector resumes; existing
pictures were kept) added **180 pictures for 12 people**, 15 each: Hugh Jackman, Benedict Cumberbatch,
Cate Blanchett, Nicole Kidman, Matt Damon, Samuel L. Jackson, Denzel Washington, Meryl Streep, Viola
Davis, Lupita Nyong'o, Kristen Stewart, Jake Gyllenhaal (rejected candidates: 190 without one dominant
face, 30 too small, 19 not JPEG, 2 duplicates). Twelve rather than four, so the set still reaches 40 if
the review drops some. **They are unreviewed:** nothing is verified until the owner reviews them
(`label_review.py serve --dataset evaluation/datasets/celebs-commons --reviewer sodiq --people "<the 12
names>"`); then a new export and a gate re-run follow.

**Reviewed (2026-10-15).** The owner reviewed the 12 people: 2 EXCLUDED, 1 UNCERTAIN (AMBIGUOUS), 7
VERIFIED with a flag (5 LOW_QUALITY, 2 MULTI_PERSON; flagged pictures are kept out of the verified set
by the tool), and stated that every photograph left unmarked is verified. The agent confirmed that
the 170 unmarked photographs all belong to those 12 people and recorded 170 `VERIFIED` decisions
through `Review.decide`, reviewer `sodiq`, note "bulk-recorded 2026-10-15 by the agent from the owner's
statement that every unmarked photograph of the 12 new people is verified". Status: 716 photographs,
all reviewed (693 verified, 9 uncertain, 14 excluded, none stale).

**New export:** `review/exports/verified-20261015T073439095195Z.json`: **48 identities with enough
images and 142 held-out queries; shortfall 0** against the owner's targets (40 identities, 80 queries).
23 photographs left out as not verified and 7 as flagged.

## Gate on the 48-identity verified set (2026-10-15, 07:35 to 07:58 UTC)

Same command as above with that export, `--people 40 --unknown 8`, workdir
`evaluation/datasets/gate-celebs-commons-48`, report `evaluation/datasets/reports/gate-celebs-commons-48.json`
(final, not partial).

| Measure | Value | Owner's threshold |
|---|---|---|
| Enrolled people / photographs placed | 40 / 453 (none lost) | 40+ identities |
| Held-out queries | 118 (at least 2 per person) | 80+, 2+ each |
| Recall@1 | 0.983 (Wilson 95% 0.940 to 0.995) | 0.85 |
| Recall@5 | 0.992 (0.954 to 0.999) | 0.95 |
| MRR | 0.986 | 0.90 |
| Same rankings after a restart | yes | 100% |
| Workflow checks | 10 of 10 | 100% |
| Library counts unchanged by the queries | yes: 453 sources, 40 identities, 453 runs (counts only) | zero unintended mutations |
| Stranger queries / accepted by the real policy | 115 from 8 people / 0 (best similarity 0.309) | |
| Cut-off read-out | 0.30: 3 strangers accepted; 0.35 to 0.55: none, known accepted correctly 97.5% at 0.35 and 0.40, 95.8% at 0.45, 91.5% at 0.50, 89.0% at 0.55 | |
| Recall@1 after the workflow and restart | 0.958: the forgotten person's queries (Denzel Washington) no longer match, by design, plus the two misses | |

The two misses: Morgan Freeman `015.jpg` (again; own identity not offered, top 0.115) and Kevin Hart
`014.jpg` (ranked third; top candidate 0.162). Both have low similarities everywhere, so the real policy
abstains rather than answering wrongly. Strangers: Brad Pitt, Chris Evans, Kristen Stewart, Margot Robbie,
Matt Damon, Meryl Streep, Michael B. Jordan, Will Smith (random, not look-alikes).

**Reading.** For the first time a **verified set meets the owner's dataset targets and every measured
provisional threshold**. This is the assisted-recognition quality bar. **TST-057B stays `BLOCKED`**: it is
*automatic* recognition, which stays off under the decision of 2026-10-14 until hard negatives (issue 177)
are measured and an owner-approved code change is made. "Zero unintended mutations" is only shown for
counts. The limits below still apply.

## Limits to carry into any claim

- The labels are Commons categories checked by one reviewer. The set is celebrity photographs (many
  likely in the recogniser's training data: a possibility, not measured) and only pictures where
  SCRFD found one dominant face, so it cannot show detector recall or unfiltered performance.
- 36 identities were below the owner's 40 in the first run; the second run (48 verified, 40 enrolled) meets it.
- Rights are unreviewed (`rights_reviewed: false`); files stay local and are never redistributed.

## Next

See `.agents/CONTEXT.md`, "Next steps (2026-10-15)".
