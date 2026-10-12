# Python 07 Read a real function

## 1. What this is and why it exists

You now know enough Python to read the most important thirty lines in the product: the function that
decides **match, new person or not sure** for one face. This lesson reads it line by line, runs it with
made-up evidence, breaks it on purpose, and shows the tests that notice. If you can do this lesson, you
can read most of `backend/app/`.

## 2. Where it lives

- The function: `IdentityReasoner.decide` in `backend/app/recognition/reasoner.py`.
- Its inputs: a `RecognitionAssessment` (`backend/app/recognition/assessment.py`): the candidates
  found in memory, grouped by identity, with the best similarity of each group and the margin
  between the first and second group.
- Its settings: a `DecisionPolicy` (the thresholds).
- Its tests: `tests/unit/test_recognition_reasoner.py` (59 tests, pure logic, no database).

## 3. How it works

The code, as it is in `main` (comments removed):

```python
def decide(self, assessment: RecognitionAssessment) -> RecognitionDecision:
    policy = self.policy

    if assessment.quality.detection_score < policy.min_detection_score:
        return abstain(Reason.LOW_QUALITY)
    if not assessment.complete:
        return abstain(Reason.RETRIEVAL_INCOMPLETE)
    if not assessment.groups:
        return create(Reason.NO_CANDIDATE)
    top = assessment.groups[0]
    if top.best_similarity >= policy.match_threshold:
        margin = assessment.margin
        if margin is not None and margin < policy.margin:
            return abstain(Reason.AMBIGUOUS_CANDIDATES)
        if top.identity_id is None:
            return abstain(Reason.UNRESOLVED_NEIGHBOUR)
        return RecognitionDecision(RecognitionOutcome.MATCH_EXISTING, Reason.MATCHED, top.identity_id, ...)
    if top.best_similarity < policy.new_identity_ceiling:
        return create(Reason.NOT_SIMILAR)
    return abstain(Reason.UNCERTAIN_SIMILARITY)
```

In plain words, top to bottom:

1. **Quality first.** A face the detector was not confident about decides nothing: `ABSTAIN / LOW_QUALITY`.
2. **Is the search trustworthy?** If candidates were dropped or the index had not caught up with the
   database, "nobody found" might just mean "not found yet", so do not trust it: `ABSTAIN / RETRIEVAL_INCOMPLETE`.
3. **Nobody to compare with** is a valid answer for a first face: `CREATE_NEW / NO_CANDIDATE`.
4. **Look at the best group.** If it is similar enough (`>= match_threshold`):
   - and the runner-up is too close (`margin < policy.margin`): `ABSTAIN / AMBIGUOUS_CANDIDATES`;
   - and the best group has no identity (an unplaced face): `ABSTAIN / UNRESOLVED_NEIGHBOUR`;
   - otherwise `MATCH_EXISTING / MATCHED`.
5. **Clearly different** (`< new_identity_ceiling`): `CREATE_NEW / NOT_SIMILAR`.
6. **In between**: `ABSTAIN / UNCERTAIN_SIMILARITY`.

Every `return` is a different decision with a recorded reason. Notice what is *absent*: no randomness,
no hidden state, no database. The function is **pure**: the same inputs always give the same answer,
which is why it can be tested exhaustively and why the answer can be explained later from the Evidence
that is stored with it.

> Note the owner's decision of 2026-10-08: `ABSTAIN` never means "new person". With automatic matching
> disabled (`match_threshold` above 1.0 and a `new_identity_ceiling` of -1), only a face with nobody to
> compare with (rule 3) creates an identity; every other face abstains and waits for you.

## 4. Try it

**Works with no models. Verified 2026-10-12.** The test file has small helpers that build evidence;
reuse them in `uv run python`:

```python
>>> from tests.unit.test_recognition_reasoner import decide, candidate, POLICY
>>> POLICY
DecisionPolicy(version='policy-test-1', min_detection_score=0.5, match_threshold=0.6, margin=0.1, new_identity_ceiling=0.3)
>>> d = decide(candidate(1, 0.9, identity=7), candidate(2, 0.6, identity=8))
>>> d.outcome.value, d.reason.value
('MATCH_EXISTING', 'MATCHED')
>>> d = decide(candidate(1, 0.9, identity=7), candidate(2, 0.85, identity=8))
>>> d.outcome.value, d.reason.value, round(d.assessment.margin, 2)
('ABSTAIN', 'AMBIGUOUS_CANDIDATES', 0.05)
>>> d = decide(candidate(1, 0.2, identity=7)); d.outcome.value, d.reason.value
('CREATE_NEW', 'NOT_SIMILAR')
>>> d = decide(candidate(1, 0.45, identity=7)); d.outcome.value, d.reason.value
('ABSTAIN', 'UNCERTAIN_SIMILARITY')
>>> d = decide(); d.outcome.value, d.reason.value
('CREATE_NEW', 'NO_CANDIDATE')
>>> from backend.app.recognition.assessment import ObservationQuality
>>> d = decide(candidate(1, 0.9, identity=7), quality=ObservationQuality(detection_score=0.3))
>>> d.outcome.value, d.reason.value
('ABSTAIN', 'LOW_QUALITY')
```

`candidate(n, similarity, identity=...)` makes one remembered face with that similarity to the query;
`decide(...)` assesses and decides with `POLICY` (match at 0.6 or more, a lead of at least 0.1,
"clearly different" below 0.3, quality gate 0.5). Walk each line back to a rule in the list above.
Each of the six lines printed above is one of the reasons.

Then run its whole test file:

```bash
uv run pytest tests/unit/test_recognition_reasoner.py -q
```

Expected: `59 passed` in about a second.

## 5. Change it

The safest possible change is a **hand mutation**: break one comparison on purpose, watch a test notice,
restore it. This is how the project checks that its tests are strong ("a test that still passes when the
code is broken is not testing anything"). On 2026-10-12 this was done and reverted:

1. In `backend/app/recognition/reasoner.py` change `if top.best_similarity >= policy.match_threshold:` to
   `if top.best_similarity > policy.match_threshold:`.
2. Run `uv run pytest tests/unit/test_recognition_reasoner.py -q`.

Expected: `2 failed, 57 passed`:
`test_a_lone_candidate_at_the_threshold_matches_it_needs_no_margin` and
`test_a_similarity_exactly_at_the_match_threshold_is_considered_for_a_match`. The tests that pin the
boundary notice that "exactly at the threshold" no longer matches.

3. Restore it: `git restore backend/app/recognition/reasoner.py`, and confirm `git status` shows nothing
   changed.

## 6. Break it on purpose

Move the quality gate (the first `if`) to just before the last `return`. Run the tests. Expected
(observed 2026-10-12): `3 failed, 56 passed`, including
`test_a_face_below_the_quality_gate_decides_nothing_whatever_the_candidates` and
`test_the_quality_gate_is_decided_before_the_retrieval_check`: a face of poor quality can now reach
`MATCH_EXISTING` before it is checked. The order of the checks *is* the policy: quality first means a
doubtful face never gets as far as being compared. Restore with `git restore` as above.

## 7. Exercises

1. Without running anything: what does `decide` return for a face with detection score 0.3 when
   `min_detection_score` is 0.5, however similar its best candidate is?
2. Same policy as `POLICY`: best similarity 0.9, runner-up 0.85. Outcome and reason?
3. Same policy: best similarity 0.45 and nothing else. Outcome and reason?
4. Same policy: the best similarity is 0.9 but the best group's `identity_id` is `None`. Outcome?
5. Write down, in your own words, why `RETRIEVAL_INCOMPLETE` is checked before `NO_CANDIDATE`.

**Answers**

1. `ABSTAIN` with reason `LOW_QUALITY`: the first check, before anything else is looked at.
2. `ABSTAIN / AMBIGUOUS_CANDIDATES`: the margin is 0.05, below the policy's 0.1.
3. `ABSTAIN / UNCERTAIN_SIMILARITY`: 0.45 is between the ceiling (0.3) and the threshold (0.6).
4. `ABSTAIN / UNRESOLVED_NEIGHBOUR` (assuming the margin is fine): an unplaced face can never be matched
   to, so the new face waits for a human.
5. If the search could have missed the true nearest face, "no candidate" might be false; treating it as
   "new person" would create a duplicate identity. Check trust first, then conclude.

## 8. Related files

- Previous: [06 Iterators, decorators and concurrency](06-iterators-decorators-concurrency.md) · [Python index](README.md) · Next: [tools](../tools/README.md)
- [`backend/app/recognition/reasoner.py`](../../../../backend/app/recognition/reasoner.py)
- [Decision policy](../../03-backend/recognition/03-decision-policy.md), [thresholds and errors](../recognition-ideas/05-thresholds-and-errors.md)
