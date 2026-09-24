# M1 PR 4: corrections and rename via Person association

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M1 (TST-013, TST-014)
- **Status:** done
- **Commits:** PR #7: `refactor(identities): share the optimistic-locked update helper`, `feat(people): add person and association use cases`, `test(people): add person use-case tests`, `docs: record m1 person corrections and rename`

## What changed

- `backend/infrastructure/db/optimistic.py`: `optimistic_locked_update`, extracted from
  `activate_identity` (PR #6). One correct implementation of PERSISTENCE_IMPLEMENTATION.md §2's
  `WHERE id = :id AND revision = :expected_revision` pattern — including the
  `synchronize_session=False` subtlety PR #6's review surfaced — instead of every feature
  re-deriving it. `activate_identity` now calls it; behaviour is unchanged (all 166 existing
  tests still pass unmodified).
- `backend/app/people/use_cases.py`:
  - `assign_identity_to_person`: links an Identity to a Person, ending any current active link
    first (§9). **Calling it again with a different Person is the correction** (TST-013): the
    old association becomes `SUPERSEDED`, never deleted, its `Evidence` untouched; a new
    `Evidence(IDENTITY_ASSIGNED_TO_PERSON)` row explains the change, with the previous person's
    id in its payload.
  - `remove_identity_from_person`: ends the current active link without creating a new one,
    recording `Evidence(IDENTITY_REMOVED_FROM_PERSON)`.
  - `rename_person`: changes only `display_name`/`normalized_name`, optimistic-locked on
    `revision` (TST-014).
- `tests/integration/test_person_use_cases.py`: 23 tests.

## Why

M1 plan step 5. Per PERSISTENCE_IMPLEMENTATION.md §9: "Assignment is an explicit use case:
lock/reload the identity, end any current active association, create the new active
association, append Evidence, and commit... This preserves why the current name differs from an
older decision" — that sentence is describing a correction using the same function repeatedly,
so no separate "correction" function was built; `assign_identity_to_person` already is one.

## Decisions

- **Corrections happen at the Person-association level, not by reassigning a
  representation's identity.** The M1 plan's own wording ("Corrections and rename **via Person
  association**") and §9's text above both point here; a representation-level re-identification
  use case is not part of this PR's scope.
- `assign_identity_to_person` requires the identity `ACTIVE` (symmetric with
  `assign_representation_to_identity`'s rule, PR #6) and the person `ACTIVE`. Reassigning to the
  *same* person is rejected as a no-op, not silently accepted.
- `remove_identity_from_person` does **not** require the identity to be `ACTIVE`: it only ends
  an existing row, so it cannot create an invalid new link regardless of the identity's current
  state. This is a deliberate asymmetry with assignment, not an oversight.
- **No `Evidence` is recorded for `rename_person`.** `identity-and-memory-model-v1.md` §38 says
  renaming "produces a historical semantic event", but the locked `EvidenceKind` enum has no
  matching value. Inventing one would be schema scope creep for this PR; recorded as CONTEXT
  open question 12 instead.
- The association's own `evidence_id` always points at the evidence that **created** that row
  (assignment), never at a later removal's evidence; a removal's evidence stands on its own,
  linked by `subject_identity_id`/`subject_person_id`.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov`: 189 passed (23 new); `backend/` coverage 100%;
  strict mypy and ruff clean. The `activate_identity` refactor changed zero test outcomes.
- Mutation checks (each reverted afterwards), all caught:
  - dropping the identity-`ACTIVE` guard on assignment → 4 tests fail;
  - dropping the person-`ACTIVE` guard → 3 tests fail;
  - dropping the same-person no-op guard → 1 test fails;
  - dropping the old association's `SUPERSEDED` transition → a DB-level `UNIQUE` violation
    surfaces instead of a clean correction (still caught, via a different exception);
  - dropping the no-active-association guard on removal → 1 test fails;
  - dropping removal's actual state change → 2 tests fail;
  - disabling `optimistic_locked_update`'s revision check entirely → 2 tests fail (proving the
    shared helper, not just its callers, is exercised).

## Open issues / follow-ups

- The rename-Evidence gap (CONTEXT open question 12).
- Merge/split (TST-015/016), the query-only recognition guard (TST-019) and property tests
  (TST-020) are the remaining M1 slices.
