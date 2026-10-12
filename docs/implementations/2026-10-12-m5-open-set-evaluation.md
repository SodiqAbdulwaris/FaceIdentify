# M5: open-set evaluation (TST-057B evidence, not a pass)

- **Date:** 2026-10-12
- **Milestone / tracker IDs:** M5 R5 follow-up; TST-057B (stays `BLOCKED`)
- **Status:** built and run once; **TST-057B is not claimed**
- **Commits:** PR to be recorded when merged

## What was built

`evaluation/assisted_recognition_gate.py` gained `--unknown N` and two reports:

- **Open set.** N people are never enrolled (taken from the identities that are not among the enrolled ones);
  every usable photograph of theirs is a query that should *not* match anyone. The report lists, apart from
  the closed-set retrieval numbers: how many strangers' top candidates reach each similarity cut-off (a false
  match if the policy accepted at that cut-off) with a Wilson 95% interval, how many enrolled people would be
  accepted rightly and wrongly at the same cut-off, the strangers' top-similarity range, and what the
  application itself decided under its real policy (`IDENTITY_ANSWER`, `POSSIBLE_PEOPLE`, `UNKNOWN`).
- **Per identity.** Queries, first-place hits and hits within five for each enrolled person.
- `partition_people` replaces the old selection: enrolled people need `--minimum-photographs`; unknown people
  may have any number. No photograph is on both sides (each distinct picture is used once, by content).
- Tests: `test_assisted_gate.py` now has 13 (selection, partition, open-set counting, per-identity, interval).

## The first run (owner-verified labels; `evaluation/datasets/reports/gate-open-set.json`)

`--people 40 --minimum-photographs 5 --unknown 12` on the export of 2026-10-12, real `buffalo_l` on CPU:

| Measure | Value |
|---|---|
| Enrolled people / enrolled photographs / closed-set queries | 9 / 61 / 18 |
| Closed-set Recall@1, Recall@5, MRR | 1.000 / 1.000 / 1.000 (Wilson 95% for the recalls: 0.824 to 1.000) |
| Strangers: people / photographs used as queries | 12 / 25 |
| Strangers' top-candidate similarity | 0.046 to 0.237 (median 0.159) |
| Strangers the application accepted as a known person (its real policy) | 0 of 25; all 25 were offered only as possible people |
| Strangers accepted at a cut-off of 0.30 or higher | 0 of 25 (Wilson 95% upper bound 0.133) |
| Enrolled people rightly top-ranked at similarity >= 0.30 / 0.50 / 0.70 | 18 / 17 / 13 of 18, none wrongly |
| Workflow checks, same rankings after restart, queries wrote nothing | 10 of 10, yes, yes |

## Reading it, and its limits

- On this set the two groups do not overlap: every stranger's best candidate (at most 0.237) scored below every
  correct known top-1 (all 18 were 0.30 or more), so a similarity cut-off above 0.24 and up to 0.30 would have
  given no false match and kept all 18 known queries. **That is a description of this set, not a chosen
  operating point**, and nothing here changes the abstain-only policy file or its guard.
- **Why it cannot be trusted further:** 9 enrolled identities and 25 stranger queries (the targets are 40 and
  far more); the strangers are people the owner could verify, i.e. the clearest photographs, and the 66
  UNCERTAIN and 90 flagged photographs (the hard cases) are not in it; strangers were not chosen to resemble the
  enrolled people (same family, same agency, similar age and appearance); 0 of 25 only bounds the false-match
  rate below about 13% at 95% confidence.
- Per-identity numbers are 1 to 3 queries each: shown for completeness, not evidence.

## What is still missing for TST-057B

1. A verified set at the targets (40 identities with 5+ images, 80+ queries): the review continues or the pool
   is justifiably expanded.
2. Hard negatives: strangers chosen to look alike, and photographs of poorer quality.
3. A decision, by the owner, on whether an automatic-acceptance policy is ever enabled; that needs the
   conservative precision rule re-run on verified labels (R5), then an explicit change to the guarded policy.
