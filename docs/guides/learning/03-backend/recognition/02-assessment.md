# Recognition 02 Assessment

## 1. What this is and why it exists

Raw candidates are representations; a decision is about *people*. Assessment groups the candidates by identity, ranks the
groups, measures the **margin** between the best two, and records the facts a reasoner needs. It creates nothing: no identity,
no evidence, no association. It only *describes the neighbourhood* of one face.

## 2. Where it lives

| Thing | Where |
|---|---|
| `assess`, `RecognitionService`, `RecognitionAssessment`, `CandidateGroup`, `GroupMember`, `ObservationQuality` | `backend/app/recognition/assessment.py` |
| Tests | `tests/integration/test_recognition_service.py` (9), grouping cases in `tests/unit/test_recognition_reasoner.py` |

## 3. How it works

- **Grouping**: all candidates of one identity form one `CandidateGroup`, scored by its **best** (highest) similarity, so an
  identity with many photographs is not favoured by their number (the code deliberately has no history-count feature until bias
  is measured). Every member keeps its own similarity and its pool, so evidence can say which representation was how near.
- **A candidate without an identity** (an accepted abstention, or a pending one) is its own group each time: it proves
  "something looks like this" but is never a target to match.
- **Ordering**: groups by best similarity, ties broken by representation id, so the result is deterministic.
- **`margin`** = best group's similarity minus the next group's; `None` with fewer than two groups.
- **`complete`** = nothing dropped and the index converged. An incomplete assessment cannot support a match or a new identity.
- **`interpretation`**: `COSINE_UNCALIBRATED`. The similarity is used as it is; nothing claims a probability. A calibrated
  interpretation would be a new value and a new assessment version (`recognition-assessment-v2`).
- **Not modelled yet**: correction constraints (a prior rejection that similarity must not overwhelm). Today a previously
  rejected identity can be matched again on similarity alone.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_recognition_service.py tests/unit/test_recognition_reasoner.py -q -k "group or margin or favoured or assessment"
```

Expected: `16 passed` (observed; the grouping cases are the first tests in `test_recognition_reasoner.py`:
`test_an_identity_with_many_representations_is_not_favoured_by_their_number`,
`test_a_candidate_without_an_identity_is_its_own_group_each_time`). In the practice library's `IDENTITY_MATCHED` evidence the
`candidates` list is exactly an assessment: rank 1 similarity `1.0` and rank 2 `0.208`, so the margin was about `0.79`.

## 5. Change it

A new fact on the assessment (say the age of the best match) is a new field, a new `ASSESSMENT_VERSION`, tests, and evidence
payload keys that older readers can ignore. Never change the meaning of a field under the same version; evidence already
stored under the old version must still read correctly.

## 6. Break it on purpose

Make grouping sum similarities instead of taking the best (scratch edit): `test_an_identity_with_many_representations_is_not_favoured_by_their_number`
fails. Restore with `git restore`.

## 7. Exercises

1. Why score a group by its best member and not by the average?
2. What is the margin of a single-group assessment?
3. Why is an identity-less candidate never a match target?
4. When is an assessment `complete`?

**Answers**

1. One good photograph should be enough; an average would punish identities with varied photographs.
2. `None`; there is no second group to measure against.
3. There is no identity to attach the face to; it can only be evidence.
4. `dropped == 0` and the index `converged`.

## 8. Related files

- Previous: [01 Retrieval](01-retrieval.md) · Next: [03 The decision policy](03-decision-policy.md)
- [`backend/app/recognition/assessment.py`](../../../../../backend/app/recognition/assessment.py)
