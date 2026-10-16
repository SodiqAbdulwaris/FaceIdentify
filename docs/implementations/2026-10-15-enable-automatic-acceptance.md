# M5: enabling automatic acceptance at an owner-approved operating point (TST-057B)

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R; TST-057B (`IN_PROGRESS`: built and verified; the live policy installed by the owner on 2026-10-15, the real-host check on it still to record)
- **Status:** partial: code, tests and analysis done; **the owner confirmed option A** (0.45 / 0.10) on 2026-10-15; verified with the real weights in a private state; the owner installed the live policy file on 2026-10-15 at 23:58 (command below; the restore copy beside it was checked to load)
- **Commits:** PR to be recorded when merged (`feat(api): admit an owner-approved matching policy`, docs commits)

## The owner's decision

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source
> recognition, TST-057B), in their words: "the we're enabling auto-acceptance, we can do that". This is
> step 5 of the 2026-10-14 decision ("an explicit, owner-approved code change"); steps 1 to 4 were met
> on 2026-10-15 (the 48-identity verified set, hard negatives, the conservative rule on a verified
> manifest with zero false accepts). The exact operating point was brought back for confirmation;
> the recommended one was threshold 0.45, margin 0.10.

> **Decision 2026-10-15:** the owner confirmed option A: "A: threshold 0.45, margin 0.10, no automatic new identity." (relayed by the
> supervising session). `APPROVED_MATCHING` already held it, so no number changed.

## What changed

- `backend/api/real.py`: `require_abstain_first` becomes `require_approved_policy`. A policy file is
  admitted when it abstains first (as before) **or when it equals, version and all four numbers, an
  entry of `APPROVED_MATCHING`**, a constant in the code. A file cannot enable matching by itself: any
  other matching policy, including one `measure_operating_point.py --write-policy` produces
  (`buffalo-l-conservative-provisional-v1`), is still refused. The `new_identity_ceiling` must stay -1
  either way: automatic *new identities* need their own approved duplicate-creation budget (ML spec
  17.2), which nobody has asked for, so a face below the threshold abstains and waits for the owner.
- `APPROVED_MATCHING` holds one entry, the recommended point:
  `buffalo-l-verified-match-v1` with `min_detection_score` 0.5, `match_threshold` 0.45, `margin` 0.10,
  `new_identity_ceiling` -1.0. If the owner chooses another option, only these numbers change.
- Tests:
  - `tests/unit/test_approved_operating_point.py` (the real `IdentityReasoner` under the approved
    policy, built from the constant): a face above the threshold with the margin is matched; below the
    threshold it abstains (`UNCERTAIN_SIMILARITY`); above it but within the margin it abstains
    (`AMBIGUOUS_CANDIDATES`); a stranger at 0.402 (the highest stranger in any recorded run), 0.309,
    0.0 or -0.2 abstains and is never made a new identity.
  - `tests/integration/test_real_profile.py`: the approved file is admitted and readiness says
    `processing_policy: READY`; the same file with a lower threshold, a smaller margin, a lower
    detection floor, a ceiling of 0, or another version is refused and readiness says `UNAVAILABLE`;
    through the whole application, a second identical face is matched automatically (one identity,
    nothing left unresolved, the run reports `automatic_matching: true`).
- `tests/e2e/test_real_host.py` (local, real weights, `-m e2e`): each test now writes its own policy
  into its private state instead of copying the installed file, so it no longer depends on what the
  machine has installed. The assisted test keeps the abstain-only policy; a new test runs the
  approved point: the second photograph of the same person is matched automatically to the first
  person's identity, and a different person's photograph scores below 0.45 and waits.
- The live policy, `local-models/state/policies/insightface-buffalo-l.json`. The live file is installed by the owner (this session's tools may not write to the main checkout), with the abstain-only file kept beside it to restore:

```json
{
 "schema_version": 1,
 "version": "buffalo-l-verified-match-v1",
 "min_detection_score": 0.5,
 "new_identity_ceiling": -1.0,
 "match_threshold": 0.45,
 "margin": 0.1
}
```

  ```bash
  cd local-models/state/policies
  cp insightface-buffalo-l.json insightface-buffalo-l.abstain-only-v1.json
  printf '%s\n' '{"schema_version": 1, "version": "buffalo-l-verified-match-v1", "min_detection_score": 0.5, "new_identity_ceiling": -1.0, "match_threshold": 0.45, "margin": 0.1}' > insightface-buffalo-l.json
  ```

  To go back to abstain-only, copy `insightface-buffalo-l.abstain-only-v1.json` over
  `insightface-buffalo-l.json`; only that one name is ever read. The policy is read on every request,
  so neither step needs a restart; runs already made keep the policy they were frozen under, so faces
  processed before it stay abstained (reprocessing them is a separate, later decision).

## The analysis

No model was run. The reasoner's rule (match when the best person scores at least the threshold
**and** leads the next person by at least the margin) was replayed over the per-query candidate lists
stored in every recorded gate report, and over the cached embeddings of the two Commons sets
(scratch script, not committed; reports under `evaluation/datasets/reports/`, Git-ignored).

### Every recorded gate run, by threshold (margins up to 0.10 change nothing measured at 0.40 and above)

Known = queries of enrolled people that were evaluated; strangers include hard negatives. "Recall" is
known queries accepted *correctly*; there were no known queries accepted wrongly at any of these points.

| Run | Labels | Known / strangers | Best stranger | 0.35 | 0.40 | **0.45** | 0.50 | 0.55 | 0.62 |
|---|---|---|---|---|---|---|---|---|---|
| LFW, 100 enrolled | unverified | 173 / 375 | 0.402 | 4 FA, 1.000 | 1 FA, 1.000 | **0 FA, 0.994** | 0, 0.994 | 0, 0.988 | 0, 0.960 |
| CelebA, 100 enrolled | unverified | 283 / 580 | 0.383 | 4 FA (3 at margin 0.05), 0.975 | 0, 0.968 | **0, 0.965** | 0, 0.954 | 0, 0.915 | 0, 0.823 |
| Commons, 36 verified (28 enrolled) | verified | 84 / 109 | 0.309 | 0, 0.976 | 0, 0.976 | **0, 0.964** | 0, 0.905 | 0, 0.869 | 0, 0.786 |
| Commons, 48 verified (40 enrolled) | verified | 118 / 115 | 0.309 | 0, 0.975 | 0, 0.975 | **0, 0.958** | 0, 0.915 | 0, 0.890 | 0, 0.814 |
| 48 + 15 look-alikes from LFW-150 | verified + LFW | 118 / 205 (90 hard) | 0.309 | 0, 0.975 | 0, 0.975 | **0, 0.958** | 0, 0.915 | 0, 0.890 | 0, 0.814 |
| 48 + 15 look-alikes from all of LFW | verified + LFW | 118 / 146 (31 hard) | 0.320 | 0, 0.975 | 0, 0.975 | **0, 0.958** | 0, 0.915 | 0, 0.890 | 0, 0.814 |

About 1,200 distinct stranger queries in all (they repeat people, so they are not independent trials).
At 0.45 none is accepted and no known person is accepted as somebody else.

**The margin.** Among known queries accepted correctly at 0.45, the smallest lead over the next person
was 0.142 (Commons 48), 0.198 (CelebA) and 0.366 (LFW), so a margin of 0.10 costs nothing measured.
It is the only protection when two similar people (siblings, a parent and a grown child) are **both**
enrolled: a face close to both then abstains as `AMBIGUOUS_CANDIDATES`. On the real processing path
the shortlist holds `recognition_k = 5` faces; when all five belong to one identity there is no second
person to measure a margin against and the threshold alone decides (the reasoner's existing rule).

### The one run that is not zero above 0.45: the first Commons set (2026-10-07)

The conservative rule on `commons-pd` (unverified Commons categories) left false accepts at 0.409,
0.409, 0.567, 0.598 and 0.615. The cached embeddings show why that set cannot be read as a model
error rate: **the same file is stored under two people** (`Kathryn_D_Sullivan/09.jpg` and
`Bruce_McCandless_II/21.jpg` have the same SHA-256 and score 1.000), and every pair above 0.55 involves
two astronaut photographs (`Story_Musgrave/23.jpg` against `Bruce_McCandless_II/05.jpg` and `06.jpg`,
`Sally_Ride/01.jpg` against `Story_Musgrave/23.jpg`), the pattern a crew photograph filed under the
wrong crew member gives. That is strong evidence of label error but **not verified by eye**; the
owner can open those files to settle it. The verified 48-identity set has no different-person pair
above 0.333 at all (686 photographs).

**No threshold is clean on every recorded run.** The table above covers the six gate runs since the
LFW import (2026-10-13 onwards). The earlier gate runs on `commons-pd` (2026-10-10:
`gate-before-review.json`, `gate-k5.json`, `gate-k50-first.json`) offered `Bruce_McCandless_II/21.jpg`
as Kathryn D. Sullivan at 1.000 with a margin of 0.74: the duplicate file above, which every threshold
and margin accepts, because it *is* the same picture under another name. Leaving that set out as
mislabelled (one proven duplicate, the other pairs unchecked by eye), every run is clean at 0.45;
keeping it, 0.62 clears the conservative rule's 0.567 to 0.615 pairs but not the duplicate.

## Options for the owner

| Option | Threshold / margin | False accepts recorded | Known people accepted automatically | Headroom over the highest stranger |
|---|---|---|---|---|
| **A (recommended)** | **0.45 / 0.10** | 0 in the six gate runs since 2026-10-13; on `commons-pd` (unverified, a proven duplicate label) the 0.567 to 0.615 pairs and the 1.000 duplicate remain | 95.8% verified set, 96.5% CelebA, 99.4% LFW | 0.048 over LFW's 0.402; 0.13 over the verified sets' 0.32 |
| B | 0.50 / 0.10 | the same as A | 91.5% verified set, 95.4% CelebA, 99.4% LFW | 0.098 over 0.402 |
| C | 0.62 / 0.10 | as A, and also above the `commons-pd` conservative-rule pairs (0.567 to 0.615); the 1.000 duplicate remains, as at any point | 81.4% verified set, 82.3% CelebA, 96.0% LFW | above every different-person score except the duplicate file |

- **A** is the point the 2026-10-14 decision named as the candidate, and the lowest threshold clean on
  every gate run with any label source. About 1 face in 25 of a known person still waits for a click.
- **B** buys twice the headroom for faces harder than celebrities (the owner's family) at the cost of
  roughly 1 extra click per 25 faces.
- **C** clears the unexplained `commons-pd` pairs (not the duplicate file, which no point can) but makes about 1 face in 5 wait, which gives back much of what
  automatic acceptance is for.

Cost asymmetry, as on 2026-10-14: a wrong automatic match silently puts a face into the wrong person's
memory (correctable, but only if noticed); an abstention costs one click.

## Risks for the owner's own photographs

None of the evaluation sets resembles a family library; the numbers above are about adult celebrities
and news photographs, many likely in the recogniser's training data (a possibility, not measured).

- **Siblings, twins, parents and children.** Relatives can score as high as the same person, and
  identical twins are beyond any face model. When both are enrolled the margin makes the face abstain
  only if the other relative is retrieved and scores within 0.10 of the best (at 0.8 against 0.6 it is
  still matched to the nearer one, which may be the wrong one; with five shortlisted faces of one person
  the other may not be retrieved at all); when only one is enrolled, the other can be matched to them.
  A wrong match between relatives stays possible either way. No measurement here covers relatives.
- **Children growing up.** Recognition across ages is weaker: a child's photographs from different
  years mostly fall *below* the threshold and abstain (safe, more clicks). The dangerous case is a
  younger sibling at the age the enrolled child's photographs were taken.
- **Old scans and poor pictures.** Scans, low resolution, blur and colour casts shift scores in ways
  none of these sets measured. The quality gate is only the detector's own score (0.5).
- **Few photographs per person.** The sets had 5 or more pictures per person; a person with one
  enrolled picture is matched on that one alone.
- **Mitigation already in place.** Every automatic match writes Evidence with its scores and policy
  version; corrections, split and "This is someone new" undo a wrong match. A screen listing
  automatic matches for review is not built (follow-up below).

## Verification

- `uv run pytest -q tests/unit/test_approved_operating_point.py tests/integration/test_real_profile.py
  tests/unit/test_conservative_policy.py`: 84 passed.
- The new tests fail without the change: with `origin/main`'s `real.py` plus only the
  `APPROVED_MATCHING` constant, 6 tests failed (the five refusal cases and the application test; the
  reasoner tests pass on the old code, as they test the existing rule at the new numbers).
- Full backend gate: see the PR description.
- `uv run pytest -m e2e tests/e2e/test_real_host.py` with the real `buffalo_l` weights on CPU
  (2026-10-15, after the confirmation): 2 passed. Three photographs only: it shows the real path
  matches and abstains under the approved point, not a rate.
- **Not verified:** any recognition on the owner's own photographs; the `commons-pd` label errors by eye.

## Open issues / follow-ups

- **Owner:** install the live policy (the command above); then TST-057B can be marked `PASSING`.
- A review list of automatic matches (a filter or badge "matched automatically") so a wrong one is
  noticed; not built.
- Measure relatives and age gaps on the owner's own labelled photographs before relying on the point
  for children.
