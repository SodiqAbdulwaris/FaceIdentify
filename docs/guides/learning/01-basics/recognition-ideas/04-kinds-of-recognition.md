# Recognition 04 Kinds of recognition

## 1. What this is and why it exists

People say "face recognition" for several different tasks. Keeping them apart is the key to understanding
the decision code, because FaceIdentify solves the hardest one, and its refusal to guess is a consequence
of that.

## 2. Where it lives

| Task | Where it shows up in the code |
|---|---|
| Verification (1:1) | the base operation: one cosine similarity; inside every identification |
| Identification (1:N) | `backend/app/recognition/retrieval.py` and `assessment.py`: nearest remembered faces, grouped by identity |
| Open-set decision | `IdentityReasoner.decide` in `backend/app/recognition/reasoner.py` (three outcomes, thresholds, abstain) |
| Face query ("who is this picture?") | `backend/app/recognition/face_query.py`, `POST /api/v1/search/face` |
| Multiple templates per person | an Identity owns *many* Representations; the best-matching one per identity scores |

## 3. How it works

- **Verification (1:1).** Are these two photos the same person? Compute one similarity and compare it
  with a threshold.
- **Identification (1:N).** Who among everyone I know is this? Compare with every known face and take the
  best.
- **Closed-set identification.** The person is guaranteed to be someone in the gallery, so the best match
  is the answer. Easy, and unrealistic: a photo library is full of strangers.
- **Open-set identification.** The person may be a stranger. The system must say "someone I know" *or*
  "nobody I know" *or* "I cannot tell". This is the real problem, and the one FaceIdentify solves. It needs
  **two thresholds** (how similar counts as a match; how different counts as clearly new), a **margin**
  (a match must clearly beat the runner-up) and a way to **abstain**.

Related ideas:

- **Re-identification** and **tracking**: following one subject across video frames or cameras. [designed]
  for M6 and M7; nothing built.
- **Clustering** (DBSCAN, HDBSCAN, agglomerative): grouping faces that probably belong together without
  labels, to discover recurring unknown people. [researched]. The built system takes a simpler route: an
  unmatched face either starts an identity (only when there is nothing at all to compare with, by the
  owner's rule) or abstains and waits for you to resolve it, and you merge duplicates by hand.
- **Template / prototype**: one summary vector per person built from many faces. The project instead
  keeps *every* representation and scores an identity by its **best-matching** one ("multiple templates"),
  and it counts the *identity*, not how many photos it has, so a person with many photos is not favoured.
- **Assisted versus automatic.** The owner decided on 2026-10-08 that the system first *assists* (ranked
  possible matches, you confirm), and that *automatic* recognition is a separate claim, blocked until a
  verified evaluation exists; that evaluation was done and the owner enabled it (TST-057B `PASSING`, confirmed 2026-10-20).

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The owner confirmed option A on 2026-10-15:** "A: threshold 0.45, margin 0.10, no automatic new identity." (`buffalo-l-verified-match-v1`; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. See "grouped by identity, best score wins" in a runnable test helper:

   ```python
   >>> from tests.unit.test_recognition_reasoner import candidate, retrieval, GOOD
   >>> from backend.app.recognition.assessment import assess
   >>> from backend.app.recognition.retrieval import Pool
   >>> made = assess(retrieval(candidate(1, 0.9, identity=7), candidate(2, 0.5, identity=8),
   ...                         candidate(3, 0.8, identity=7, pool=Pool.RUN_LOCAL)), GOOD)
   >>> [(str(g.identity_id)[-1], round(g.best_similarity, 2), len(g.members)) for g in made.groups]
   [('7', 0.9, 2), ('8', 0.5, 1)]
   >>> round(made.margin, 2)
   0.4
   ```

   Identity 7 has two remembered faces (0.9 and 0.8) and scores by its best (0.9); the margin to the next
   identity is 0.4.
2. A person with many photos is not favoured:

   ```python
   >>> crowd = [candidate(n, 0.7, identity=7) for n in range(4)]
   >>> lone = candidate(9, 0.75, identity=8)
   >>> [str(g.identity_id)[-1] for g in assess(retrieval(*crowd, lone), GOOD).groups]
   ['8', '7']
   ```

   Four faces at 0.7 lose to one face at 0.75. (This is `test_an_identity_with_many_representations_is_not_favoured_by_their_number`.)
3. Run the whole assessment and reasoner file: `uv run pytest tests/unit/test_recognition_reasoner.py -q` (`59 passed`).
4. See the assisted workflow as a route: with the backend from [lesson 07](../../00-start-here/07-run-it-and-see-it-work.md)
   running, the face search for a picture returns `possible_people` (ranked identities with their similarity) next to
   `identity_answer` (set only when the policy would accept a match).

## 5. Change it

The behaviour you may be tempted to change is *which identity wins*. Do not edit `assessment.py` to try it;
the rule is pinned by the tests above and is a recorded design decision (identity-level scoring, spec
`identity-and-memory-model-v1.md` and the Identity Decision Engine plan). The safe experiment is the
opposite: change the *inputs* in step 1 (make identity 8's face 0.95) and watch the groups reorder. For a
code-level change, follow the route in [decision policy](../../03-backend/recognition/03-decision-policy.md).

## 6. Break it on purpose

Pass an unplaced neighbour (a candidate with no identity) as the best match, after
`from tests.unit.test_recognition_reasoner import decide, candidate`: `decide(candidate(1, 0.9))` (the identity
defaults to `None`). Expected: `ABSTAIN / UNRESOLVED_NEIGHBOUR`. An
unplaced face can never be matched to, which prevents a face from silently attaching to nothing.

## 7. Exercises

1. Which of the four problems is "who is this stranger's photo?" when the person may not be known?
2. Why does the system score an identity by its best face and not by the average or the count?
3. What is the difference between *assisted* and *automatic* recognition in this project?
4. Why is closed-set identification unsuitable for a photo library?

**Answers**

1. Open-set identification.
2. The best face is the strongest evidence of "same person" (a different angle or age may match well while
   the average is dragged down); counts would favour people with many photos.
3. Assisted ranks possible matches and you confirm (TST-057A); automatic assigns without you and was not
   claimed until its quality was measured on verified data (TST-057B, now `PASSING`).
4. It assumes the person is always known; a library has many strangers.

## 8. Related files

- Previous: [03 The face pipeline](03-the-face-pipeline.md) · Next: [05 Thresholds and errors](05-thresholds-and-errors.md)
- [`docs/specs/identity-and-memory-model-v1.md`](../../../../specs/identity-and-memory-model-v1.md), [`docs/plans/IDENTITY_DECISION_ENGINE_PLAN.md`](../../../../plans/IDENTITY_DECISION_ENGINE_PLAN.md)
- [Recognition in the backend](../../03-backend/recognition/README.md)
