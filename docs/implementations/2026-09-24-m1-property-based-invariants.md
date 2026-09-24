# M1 PR 7: property-based operation-sequence invariants

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M1 (TST-020) — completes M1
- **Status:** done
- **Commits:** PR #10: `test(identities): add property-based operation-sequence invariants`,
  `docs: record m1 property-based invariants`

## What changed

- `tests/property/test_identity_lifecycle_invariants.py`: a Hypothesis `RuleBasedStateMachine`
  (`IdentityLifecycleMachine`). Each example gets its own real, file-backed SQLite database
  (production engine/pragmas via `create_sqlite_engine`), and generates sequences of the full set
  of Identity Manager operations that exist: create a PENDING identity, activate it, create a
  PENDING representation, assign it to an ACTIVE identity, create a Person, assign/remove an
  Identity-Person link, rename a Person, merge two ACTIVE identities, and split representations
  off one into a new identity. Four `@invariant()` checks run after every single step:
  - **`revisions_match_the_database`** (ID-01/PER-01): each tracked Identity's and Person's
    revision matches an independently predicted count of successful revision-bumping calls on it
    — not merely what the last call happened to report back.
  - **`evidence_is_append_only`** (OBS-03/ID-03): the `evidence` table's row count never
    decreases.
  - **`active_representations_are_ann_eligible`** (§20): no `ACTIVE` representation is ever
    missing an `ann_key`.
  - **`a_query_creates_no_persistent_state`** (SEARCH-01): calling `resolve_recognition_candidates`
    with the run's known identity ids plus one unknown id never changes any table's row count, at
    any point in the sequence.

## Why

M1 plan step 8 (last remaining M1 slice; `TESTING_IMPLEMENTATION_TRACKER.md` TST-020).
`TESTING_STRATEGY.md` §6.3: "Use Hypothesis to generate valid operation sequences involving
identity creation, assignment, correction, merging and deletion. Verify critical invariants after
every operation." This is the one M1 test that exercises the Identity Manager as a whole system
under many generated interleavings, rather than one use case in isolation.

## Decisions

- **No `deletion`/`forget` operation is generated.** No such use case exists yet in the codebase
  (a later milestone; `docs/specs/API and Contracts.md` §116 is explicitly out of scope for now).
  The state machine's operations are the complete set that does exist: create, activate, assign,
  assign/remove/rename Person, merge, split — plus the read-only recognition guard, exercised as
  an invariant rather than a mutating rule, since it must never be one.
- **A query is an invariant, not a rule.** `resolve_recognition_candidates` never writes, so
  checking it after *every* step (not just once) directly proves SEARCH-01 holds continuously
  across the whole generated history, not just at one arbitrary point.
- **Revision expectations are predicted independently, not read back from the call's own
  return value.** The first version of `revisions_match_the_database` set the mirror value from
  what `activate_identity`/`rename_person` returned, which made the check tautological — a bug
  that skipped the revision bump entirely would still "match" because both sides read the same
  (wrong) row. Caught by deliberately mutating `optimistic_locked_update` to drop the revision
  increment: the original invariant did not fail; the fixed one (`self.revision[id] += 1`,
  predicted before the call) failed immediately, on the smallest possible shrunk example (create
  + activate). Fixed before this PR's own mutation-testing pass, not found by a later reviewer.
- **Each example builds a real file-backed SQLite database from scratch**, reusing
  `create_sqlite_engine`/`Base.metadata.create_all` and the existing `ModelFactory` for
  representation-space/observation scaffolding — not an in-memory model of the schema — so this
  test exercises the actual CHECK constraints, foreign keys, and `synchronize_session=False`
  session-caching subtleties the unit tests already cover individually, but now under generated,
  interleaved sequences instead of hand-written scenarios.
- **`stateful_step_count=20`, `max_examples=25`** (CI profile derandomizes on top of that). Kept
  deliberately modest since this suite runs by default on every `pytest` invocation (the
  `property` marker isn't excluded like `e2e`/`ml_eval`/`benchmark`/`hardware`); a much larger
  budget was tried locally (`max_examples=200`, `stateful_step_count=40`, ~57s) and found no
  further issues, so the smaller default budget is a genuine speed/coverage tradeoff, not an
  untested one.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 238 passed (1 new —
  a single stateful `TestCase.runTest`, internally covering ~500 generated operation-sequence
  steps across its 25 examples — no regressions in the prior 237); `backend/` coverage 100%;
  strict mypy and ruff clean.
- A stress run outside the default budget (`HYPOTHESIS_PROFILE=dev`, `max_examples=200`,
  `stateful_step_count=40`, ~57s): passed, no further issues found.
- Mutation checks against the three invariants with a corresponding guard to break (each reverted
  immediately afterwards, confirmed byte-identical to the original via `diff`):
  - dropping the revision increment in `optimistic_locked_update` → caught by
    `revisions_match_the_database`, shrunk to the minimal `create` + `activate` sequence;
  - dropping `ann_key` assignment in `assign_representation_to_identity` → caught (a DB
    `CHECK constraint failed: ck_representations_active_eligible` surfaces, not the invariant's
    own assertion — the schema backstops the guard);
  - adding a spurious `Evidence` insert inside `resolve_recognition_candidates` → caught by
    `a_query_creates_no_persistent_state` on the very first invariant check.
  - `evidence_is_append_only` was not mutation-tested: no code path in the repository deletes an
    `Evidence` row, so there is no real line to break; the invariant exists to catch a future
    regression, not to close an existing gap.

## Independent review

Not yet run at the time of writing this entry; see the PR for the review outcome and any
follow-up this entry doesn't yet reflect.

## Open issues / follow-ups

- **M1 is now complete** (TST-011 through TST-020, all `PASSING`). M2 (Alembic migrations,
  `backend/alembic/` revision `0001_initial_schema`, switching `sqlite_engine` from `create_all`
  to real migrations, TST-032) is next per `.agents/CONTEXT.md`.
- If a `forget`/delete use case is added in a later milestone, this state machine should gain a
  corresponding rule and any invariant its introduction requires (e.g. that a forgotten identity's
  representations lose ANN eligibility).
