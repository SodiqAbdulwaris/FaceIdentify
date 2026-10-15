# Recognition 03 The decision policy

## 1. What this is and why it exists

The `IdentityReasoner` turns an assessment and a **policy** into one of three outcomes: `MATCH_EXISTING`, `CREATE_NEW`,
`ABSTAIN`, always with a *reason*. The central idea is conservative: **when unsure, abstain**. An abstention ("no identity
decided") is a first-class result, never a low-confidence guess. A wrong automatic match merges two people's memories; an
abstention costs a click. The thresholds are *configuration*, supplied by the frozen run snapshot and supported by recorded
evaluation, never constants in the code.

## 2. Where it lives

| Thing | Where |
|---|---|
| `IdentityReasoner`, `DecisionPolicy`, `RecognitionOutcome`, `Reason`, `RecognitionDecision` | `backend/app/recognition/reasoner.py` |
| The policy gate for the real profile (abstain-first or an owner-approved operating point) | `require_approved_policy` and `APPROVED_MATCHING` in `backend/api/real.py` |
| Tests | `tests/unit/test_recognition_reasoner.py` (37) |
| Measuring the numbers | [evaluation lessons](../../06-evaluation-and-operations/02-measure-operating-point.md) |

## 3. How it works

A policy has a `version` and four numbers: `min_detection_score` (the quality gate), `match_threshold`, `margin` (the least
lead over the next group) and `new_identity_ceiling`. It must satisfy `-1 <= new_identity_ceiling <= match_threshold <= 2` and
`0 < margin <= 2`. A `match_threshold` above 1 can never be reached (a cosine similarity never exceeds 1), which is how
**automatic matching is turned off** (`automatic_matching` is `match_threshold <= 1`).

The rules, in order (first that applies wins):

| # | If | Outcome | Reason |
|---|---|---|---|
| 1 | detection score below the gate | `ABSTAIN` | `LOW_QUALITY` |
| 2 | assessment not complete (dropped candidates or index behind) | `ABSTAIN` | `RETRIEVAL_INCOMPLETE` |
| 3 | no candidates at all | `CREATE_NEW` | `NO_CANDIDATE` |
| 4 | best similarity at or above `match_threshold`, but margin to the next group below `margin` | `ABSTAIN` | `AMBIGUOUS_CANDIDATES` |
| 5 | ... and the best group has no identity | `ABSTAIN` | `UNRESOLVED_NEIGHBOUR` |
| 6 | ... otherwise | `MATCH_EXISTING` | `MATCHED` |
| 7 | best similarity below `new_identity_ceiling` | `CREATE_NEW` | `NOT_SIMILAR` |
| 8 | in between | `ABSTAIN` | `UNCERTAIN_SIMILARITY` |

A match needs a strictly positive margin so two identities at the same similarity cannot be separated by list order.

**The abstain-only policy.** Until a verified evaluation exists, the real profile accepts a policy only with
`match_threshold` above 1 **and** `new_identity_ceiling` of exactly `-1` ([profiles](../architecture/04-profiles.md)). Rules 4 to 7
then never fire: every face abstains, **except** the empty-library case (rule 3): with nothing to compare against, a first face
is still a valid unknown and creates an identity.

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The operating point is pending owner confirmation** (recommended: threshold 0.45, margin 0.10; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md)); until it is confirmed and the policy file is installed, the running application stays abstain-only and TST-057B stays `BLOCKED`.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Run the reasoner on hand-made assessments (paste into a terminal in the repository
folder; the script is read from standard input so the imports find the repository):

```bash
uv run python - <<'EOF'
import uuid
from backend.app.recognition.assessment import CandidateGroup, GroupMember, ObservationQuality, RecognitionAssessment
from backend.app.recognition.reasoner import DecisionPolicy, IdentityReasoner
from backend.app.recognition.retrieval import Pool

def assessment(sims, score=0.9, dropped=0, converged=True, orphan_first=False):
    groups = tuple(
        CandidateGroup(None if (orphan_first and i == 0) else uuid.uuid4(),
                       (GroupMember(uuid.uuid4(), Pool.GLOBAL, s),))
        for i, s in enumerate(sims))
    return RecognitionAssessment("demo", "COSINE_UNCALIBRATED", uuid.uuid4(), ObservationQuality(score),
                                 5, len(sims), dropped, converged, groups)

policy = DecisionPolicy("practice", min_detection_score=0.5, match_threshold=0.8, margin=0.1, new_identity_ceiling=0.4)
abstain_only = DecisionPolicy("abstain-only", 0.5, 2.0, 2.0, -1.0)
cases = [
    ("low quality face", policy, assessment([0.95], score=0.2)),
    ("index behind", policy, assessment([0.95], converged=False)),
    ("empty library", policy, assessment([])),
    ("clear match", policy, assessment([0.92, 0.30])),
    ("two close rivals", policy, assessment([0.92, 0.88])),
    ("nearest has no identity", policy, assessment([0.92, 0.30], orphan_first=True)),
    ("clearly someone new", policy, assessment([0.20])),
    ("in between", policy, assessment([0.60])),
    ("abstain-only: clear match", abstain_only, assessment([0.99, 0.10])),
    ("abstain-only: empty library", abstain_only, assessment([])),
    ("abstain-only: far away", abstain_only, assessment([0.05])),
]
for name, pol, a in cases:
    d = IdentityReasoner(pol).decide(a)
    print(f"{name:28} -> {d.outcome.value:15} {d.reason.value}")
EOF
```

Observed:

```text
low quality face             -> ABSTAIN         LOW_QUALITY
index behind                 -> ABSTAIN         RETRIEVAL_INCOMPLETE
empty library                -> CREATE_NEW      NO_CANDIDATE
clear match                  -> MATCH_EXISTING  MATCHED
two close rivals             -> ABSTAIN         AMBIGUOUS_CANDIDATES
nearest has no identity      -> ABSTAIN         UNRESOLVED_NEIGHBOUR
clearly someone new          -> CREATE_NEW      NOT_SIMILAR
in between                   -> ABSTAIN         UNCERTAIN_SIMILARITY
abstain-only: clear match    -> ABSTAIN         UNCERTAIN_SIMILARITY
abstain-only: empty library  -> CREATE_NEW      NO_CANDIDATE
abstain-only: far away       -> ABSTAIN         UNCERTAIN_SIMILARITY
```

Look hard at the last three: even a `0.99` similarity abstains under the abstain-only policy, and a far-away face abstains
too, but an empty library still creates (the `NO_CANDIDATE` rule runs before any threshold). Then run the tests:
`uv run pytest tests/unit/test_recognition_reasoner.py -q`.

## 5. Change it

The safe change is to the *numbers in your script*, not the code: change `match_threshold` to `0.95` and watch "clear match"
become `UNCERTAIN_SIMILARITY`. Changing a rule in `reasoner.py` is a recognition-behaviour change: it needs the failing test first,
an evaluation, and an owner decision; admitting a policy that can match in the real profile is gated on a verified evaluation
([operating point](../../06-evaluation-and-operations/02-measure-operating-point.md)).

## 6. Break it on purpose

Swap rules 3 and 2 in your head: an unconverged index with no candidates would `CREATE_NEW`, producing a duplicate identity for
a person the index simply had not yet learned. That is why `RETRIEVAL_INCOMPLETE` is checked first. Try it on paper with the
"index behind" case and an empty list.

## 7. Exercises

1. Which rule makes automatic matching impossible, and how?
2. Why does the abstain-only policy still create an identity for the first face?
3. Why must a match have a margin?
4. Where do the thresholds come from?

**Answers**

1. A `match_threshold` above 1: no similarity reaches it (rules 4 to 6 never fire).
2. With no candidates the face is a valid unknown (`NO_CANDIDATE`), checked before any threshold.
3. Without a lead, two identities at the same similarity would be separated only by list order.
4. The run's frozen snapshot, supported by recorded evaluation; the code ships no defaults.

## 8. Related files

- Previous: [02 Assessment](02-assessment.md) · Next: [04 Decisions in memory](04-decisions-in-memory.md)
- [`backend/app/recognition/reasoner.py`](../../../../../backend/app/recognition/reasoner.py), [thresholds and errors](../../01-basics/recognition-ideas/05-thresholds-and-errors.md)
