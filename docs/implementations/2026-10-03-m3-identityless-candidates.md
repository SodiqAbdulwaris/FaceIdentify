# M3: readers accept an identity-less ACTIVE candidate (step 11, second part)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 (step 11); TST-030 readers, TST-040
- **Status:** done: the readers. The writers (the PENDING-output writer, the acceptance use case, issue 66) are the rest of step 11.
- **Commits:** PR (this branch): `feat(memory): accept identity-less active candidates`

## What changed
Revision 0005 lets an accepted `ABSTAIN` representation be `ACTIVE` with no identity (decision 2026-10-02). Four readers joined `identities` with an inner join and so would have silently dropped it from every index and from retrieval:
- `resolve_ann_candidates` (`backend/app/identities/use_cases.py`): outer join; a candidate is kept if it is `ACTIVE` and has no identity, or an `ACTIVE` identity; `RecognitionCandidate.identity_id` is optional (None: evidence only, never a target to match).
- `IndexCoordinator._active_keys` (the staleness check) and `_active_entries` (what a rebuild streams): outer join and the same rule, so a rebuild includes the abstention and a sound index is not seen as stale because of it.
- `IndexCoordinator._apply_one` (an `ADD`): eligibility is `ACTIVE` and (no identity, or an `ACTIVE` one); an identity that exists and is not `ACTIVE` stays ineligible.
- Docstrings (the coordinator, `resolve_ann_candidates`, the property test's invariant).
Everything else is unchanged: a representation in any other state, in another space, or held by an identity that is merged, split, forgotten or deleted is still dropped.

## Verification
- New tests: revalidation keeps an accepted abstention with identity None (and the order of a mixed list), drops an identity-less one in any other state or in another space; the coordinator indexes one by an `ADD` (after an index exists, so a rebuild cannot hide a wrong `ADD`) and by a rebuild and does not rebuild again as stale, and an identity that is not `ACTIVE` stays ineligible beside it; retrieval returns one as a global candidate with no identity; end to end, a face near one is `ABSTAIN` / `UNRESOLVED_NEIGHBOUR`.
- Mutation pass: 7 original mutations (each join back to inner, the rule weakened or loosened, the `ADD` check); the first run left one (the `ADD` test passed because the first build of an index is a rebuild), which led to the stronger test; none survive. The post-rebase gate also mutated the candidate revalidation outer join and the `ADD` eligibility predicate: their focused abstention tests failed, then both files were restored to their recorded SHA-256 values.
- Full gate (post-rebase, serialized with the CI Hypothesis profile): 2168 passed, 100% coverage. The process-sensitive supervisor module was additionally repeated three times: 33 passed each run.
- Independent review correction: aligned the retrieval and coordinator module docstrings and the
  TST-040 tracker text with the implemented accepted-`ABSTAIN` eligibility rule.

## Open issues / follow-ups
- Step 11 continues: issue 66 (the unit-of-work move), the PENDING-output writer, the acceptance use case.
