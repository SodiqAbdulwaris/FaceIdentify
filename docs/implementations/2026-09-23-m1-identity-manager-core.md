# M1 PR 3: Identity Manager core

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 (TST-011, TST-012, TST-017, TST-018)
- **Status:** done
- **Commits:** PR #6: `feat(identities): add identity manager core use cases`, `test(identities): add identity manager use-case tests`, `docs: record m1 identity manager core`

## What changed

- `backend/app/identities/use_cases.py`: the first Identity Manager functions, per
  `IDENTITY_DECISION_ENGINE_PLAN.md` §1 ("The Identity Manager is authoritative for identity
  lifecycle... A decision engine estimates evidence; it does not create, merge, confirm, or
  delete identities directly"):
  - `create_pending_identity`: a new `PENDING` identity.
  - `activate_identity`: `PENDING` → `ACTIVE`, optimistic-locked on `revision`
    (`WHERE id = :id AND revision = :expected`, per PERSISTENCE_IMPLEMENTATION.md §2).
  - `allocate_ann_key`: the guarded per-space sequence from §6.3, using `INSERT OR IGNORE` to
    lazily create the sequence row and `UPDATE ... RETURNING` to allocate atomically.
  - `assign_representation_to_identity`: the one place a representation becomes ANN-eligible.
    Validates the representation is `PENDING` and the identity is `ACTIVE`, then in one
    transaction: activates the representation, allocates its `ann_key`, writes `Evidence` (kind
    `IDENTITY_CREATED` or `IDENTITY_MATCHED`, caller-supplied) with its `EvidenceRepresentation`
    link, and creates the durable `ADD` `IndexOperation` (§1 rule 4: the index intent commits in
    the same transaction as the change that requires it).
- `tests/integration/test_identity_manager.py`: 24 tests.

## Why

First slice of Identity Manager logic (M1 plan, step 4 in `.agents/CONTEXT.md`). No ML pipeline
exists yet, so — as the decision engine plan requires — these use cases take the recognition
*decision* as an explicit parameter (`identity_id`, `evidence_kind`) rather than computing one;
a future decision engine calls into this same Identity Manager.

## Decisions

- `evidence_kind` is restricted to `IDENTITY_CREATED`/`IDENTITY_MATCHED`: the two decisions this
  use case can express. Other kinds (`USER_CORRECTION`, merge/split/forget kinds) belong to
  later use cases not yet built.
- `allocate_ann_key` creates its `ann_key_sequences` row lazily on first use. No spec text
  assigns that responsibility to `RepresentationSpace` creation (PR #4 didn't do it either).
- Optimistic locking is implemented as a literal `WHERE id = :id AND revision = :expected`
  Core `UPDATE`, per §2's own wording, not SQLAlchemy's `version_id_col` (which would need
  every revisioned model updated consistently — out of scope here).
- A **bulk Core `UPDATE` bypasses the ORM's normal attribute tracking.** `activate_identity`'s
  final read uses `session.get(..., populate_existing=True)`; without it, an already-loaded
  `Identity` in the session's identity map (as in every test, which creates the row and then
  activates it) kept showing its pre-update `activated_at`. Caught by
  `test_activation_changes_state_but_never_the_identifier` before the fix went in.
- **A real design tension, found while testing, not fixed here:** `representations.ann_key` has
  a table-wide `UNIQUE` constraint (PR #4), but `ann_key_sequences` allocates independently per
  `representation_space_id`, so two different spaces can legitimately both allocate key 1. V1's
  single-preferred-space scope makes this unreachable today. Recorded as CONTEXT open question
  12, not fixed, since it would mean changing already-merged PR #4 schema — a decision for the
  owner before M3.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov`: 164 passed; `backend/` coverage 100%; strict mypy
  and ruff clean.
- Mutation checks (each reverted afterwards), all caught:
  - removing `populate_existing=True` → the stale-`activated_at` test fails;
  - removing the PENDING-representation guard → a DB-level UNIQUE violation surfaces instead of
    the intended domain error (still caught, just via a different exception);
  - removing the ACTIVE-identity guard → 5 tests fail;
  - corrupting `activate`'s `WHERE state = PENDING` guard → 14 tests fail;
  - no longer bumping `revision` on activation → 2 tests fail;
  - moving `allocate_ann_key` before validation → the no-partial-state test fails for exactly
    the two rejection paths that occur after representation lookup, confirming the guard order
    matters and is tested.

## Open issues / follow-ups

- The `ann_key` uniqueness tension above (CONTEXT open question 12).
- Corrections (TST-013), rename (TST-014), merge/split (TST-015/016), the query-only guard
  (TST-019) and property tests (TST-020) are the remaining M1 slices.
