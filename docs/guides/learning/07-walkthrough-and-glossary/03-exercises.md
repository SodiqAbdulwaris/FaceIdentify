# Walkthrough 03 Exercises

## 1. What this is and why it exists

Eight tasks, each with an answer you can verify by running something. They revise the whole guide in an order that is mostly easy to hard.

## 2. Where it lives

The files named in each exercise.

## 3. How it works

1. **Cosine.** In `uv run python`, compute the cosine similarity of `[1, 0]` and `[1, 1]` with NumPy.
2. **The reasoner on paper.** Open `backend/app/recognition/reasoner.py`. With a policy that has quality gate 0.5, match threshold 0.35, margin 0.1 and ceiling `-1`, write the outcome and reason for: a best similarity of 0.2; a best of 0.9 with no runner-up; no candidates at all.
3. **Hand mutation.** Run `uv run pytest tests/unit/test_recognition_reasoner.py -q`. In `reasoner.py` change `>=` to `>` in the match check, run again, read which tests fail, and restore the file with `git restore`.
4. **Read a database.** Build the practice library ([start-here 07](../00-start-here/07-run-it-and-see-it-work.md)), then with `q.py` ([domain README](../03-backend/domain/README.md)) count rows by `state` in `sources`, `observations` and `identities`.
5. **Why does an event refresh identities?** In `frontend/src/api/invalidation.ts`, explain why a `processing_run.updated` event invalidates the identities list as well as the run.
6. **A measurement.** Read `docs/research/measured-operating-point.md` and explain why 100% precision on the selection half did not mean the policy was good.
7. **Dependency injection.** Find three places where a function takes `clock` or `new_id` as a parameter and say what that makes possible in the tests.
8. **Derived data.** What would be lost, and what would not, if the vector index files were deleted while the app is closed?

## 4. Try it

**Works with no models. Verified 2026-10-12** for 1, 2, 3 and 4. Answers:

1. About `0.707`: `a @ b / (norm(a) * norm(b))` with `a = [1, 0]`, `b = [1, 1]` printed `0.707` (observed).
2. Observed by running the reasoner on those inputs: best 0.2 gives `ABSTAIN` `UNCERTAIN_SIMILARITY` (below the match threshold 0.35, but not below the ceiling `-1`); a lone 0.9 gives `MATCH_EXISTING` `MATCHED` (no runner-up, so no margin is needed); no candidates gives `CREATE_NEW` `NO_CANDIDATE`. (The runner is in [decision policy](../03-backend/recognition/03-decision-policy.md).)
3. Observed: `2 failed, 57 passed`. The failing tests are `test_a_lone_candidate_at_the_threshold_matches_it_needs_no_margin` and `test_a_similarity_exactly_at_the_match_threshold_is_considered_for_a_match`: the boundary is pinned by tests, which is what a good test suite does.
4. In the practice library after processing three pictures: sources 3 `ACTIVE`; observations 3 `ACTIVE`; identities 2 `ACTIVE` ([domain README](../03-backend/domain/README.md) shows the counts).
5. A run being accepted creates and grows identities, changes a person's identity count and the faces on every open person page, so those queries are stale too; that is the list in `staleBecauseOf`.
6. The threshold was chosen on the same 100 queries it scored; on the held-out half (121 queries) the same rule produced false accepts, and the interval was wide. A number that wins on the data that chose it says little about new data.
7. For example `clock` and `new_id` in `ImportSourceUseCase` and `AcceptProcessingRunUseCase`: tests pass a fixed clock and a counter so timestamps and ids are predictable, and the same input gives the same rows.
8. Nothing authoritative is lost: the index is derived, and it is rebuilt from the database at the next start (verified for a corrupted index: it is quarantined and rebuilt, the backend becomes `READY`; [vector index](../02-data-and-storage/06-vector-index-and-outbox.md)).

## 5. Change it

Make a ninth exercise of your own from a lesson you found hard, with an answer you checked by running something, and add it to your notes.

## 6. Break it on purpose

Exercise 3 is the practice of breaking on purpose; do the same to one rule in `status.ts` and read which front-end test fails.

## 7. Exercises

(These are the exercises. The answers are in section 4.)

## 8. Related files

- Previous: [02](02-reading-path.md) · Next: [04 Glossary](04-glossary.md)
