# M1 PR 5: identity-level merge and split

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M1 (TST-015, TST-016)
- **Status:** done
- **Commits:** PR #8: `feat(identities): add merge and split use cases`, `test(identities): add
  merge and split tests`, `docs: record m1 merge and split`

## What changed

- `backend/app/identities/use_cases.py`:
  - `merge_identities(session, losing_identity_id, surviving_identity_id, *, expected_revision,
    new_id, clock)`: merges one Identity into another (§114). The losing identity's row is never
    deleted — it becomes `MERGED` with `merged_into_identity_id` set. Its ACTIVE representations
    move to the survivor via a bulk `UPDATE` (their `ann_key` untouched). The Person relationship
    is reconciled: the survivor's own active link always wins; if only the loser had one, it
    carries over to the survivor (new `Evidence` + `IdentityPersonAssociation`); the loser's own
    link is always ended (`SUPERSEDED`). One `Evidence(IDENTITY_MERGED)` and one
    `IdentityLineage(MERGED_INTO)` record the merge.
  - `split_identity(session, source_identity_id, representation_ids, *, new_id, clock)`: moves
    caller-selected representations off an Identity into a brand-new one (§115, §19.2). The new
    identity is created directly `ACTIVE`. The source keeps everything else and stays `ACTIVE`.
    One `Evidence(IDENTITY_SPLIT)` and one `IdentityLineage(SPLIT_FROM)` record the split.
  - `_active_association` (private duplicate of `people/use_cases.py`'s helper, to avoid a
    circular import) and `_reconcile_person_on_merge`.
- `tests/integration/test_identity_merge_split.py`: 34 tests.

## Why

M1 plan step 7 (done ahead of step 6, per explicit user sequencing: "PR 5: merge and split"
before the query-only recognition guard). Per `IDENTITY_DECISION_ENGINE_PLAN.md` §1, the Identity
Manager is authoritative for these mutations; no decision engine exists yet, so both functions
take the caller's already-made decision (which identity survives, which representations move) as
input rather than computing one.

## Decisions

- **Merge is Identity-level, pairwise-only.** `identity-and-memory-model-v1.md` §18 (decision
  2026-09-23) downgrades Person-level merge to conceptual-only. An N-way merge composes from
  calling `merge_identities` once per losing identity — each call is independently atomic and
  history-preserving, so this reaches the same end state as a single N-way operation without
  inventing a tie-breaking policy for several losing identities' conflicting Person links.
  `test_chained_pairwise_merges_reach_one_survivor` proves the composition.
- **The losing identity's row is never deleted.** It becomes `MERGED` with
  `merged_into_identity_id` pointing at the survivor — its id and evidence history survive, only
  its `identity_lineage`/`Evidence` explain what happened to it.
- **The survivor's own Person link always wins on merge.** Only if the survivor has no active
  link does the loser's carry over. This was the simplest reading that needed no invented
  precedence rule beyond "the identity that keeps existing keeps naming authority it already has."
- **The new split identity is created directly `ACTIVE`, not `PENDING`.** Unlike a
  recognition-created identity (§7: "only an accepted processing run may activate a pending
  identity"), a split is an already-decided human action with no processing run to accept it.
- **`IdentityState.SPLIT` is used by neither identity.** No spec text says which identity a split
  should mark, and §19.2's conceptual example has the source keep some of its own evidence and
  stay current — so nothing here is retired. Recorded as CONTEXT open question 15 rather than
  guessed.
- **Neither operation moves `Occurrence` rows.** Only test factories create `Occurrence` rows
  today; no production pathway does. Recorded as CONTEXT open question 16 for whichever future
  work adds one.
- **Neither operation creates a new `IndexOperation`.** Per §23, ANN eligibility depends on
  `ann_key` presence, not `identity_id`; ownership changes without touching `ann_key`, so there is
  nothing for the index worker to (re)do.
- **`expected_revision` on merge guards only the losing identity's own row** — the one row a
  merge actually changes state on. The survivor's row is never written by a merge, so it takes no
  revision parameter.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 221 passed (34 new,
  no regressions in the prior 187); `backend/` coverage 100%; strict mypy and ruff clean.
- Mutation checks (each reverted immediately afterwards, confirmed byte-identical to the original
  via `diff`), all caught by the test suite:
  - dropping the self-merge guard → 2 tests fail (a DB `CHECK constraint failed` surfaces, not the
    domain error — the DB backstops the app-level guard);
  - dropping the survivor-`ACTIVE` guard → 2 tests fail;
  - dropping the loser-`ACTIVE` guard → 5 tests fail;
  - disabling the survivor-wins branch of Person reconciliation → 1 test fails;
  - dropping the loser association's `SUPERSEDED` transition → 2 tests fail;
  - dropping the `state == ACTIVE` filter on the representation bulk-move → not caught by the
    original suite; added `test_merge_does_not_move_the_losers_non_active_representations`, which
    then caught it;
  - dropping the stale-revision raise on the loser's finalizing update → 1 test fails;
  - dropping the split source-exists guard → 1 test fails (`AttributeError` on `None`);
  - dropping the split source-`ACTIVE` guard → 1 test fails;
  - dropping the empty-selection guard → 1 test fails;
  - dropping the representation-exists guard → 1 test fails (`AttributeError` on `None`);
  - dropping the representation-belongs-to-source guard → 3 tests fail;
  - dropping the representation-`ACTIVE` guard → 1 test fails;
  - creating the new split identity as `PENDING` instead of `ACTIVE` → 1 test fails.

## Independent review

Not yet run at the time of writing this entry; see the PR for the review outcome and any
follow-up this table doesn't yet reflect.

## Open issues / follow-ups

- CONTEXT open questions 15 (`IdentityState.SPLIT` never assigned) and 16 (`Occurrence` rows not
  moved by merge/split).
- The query-only recognition guard (TST-019) and property tests (TST-020) are the remaining M1
  slices.
