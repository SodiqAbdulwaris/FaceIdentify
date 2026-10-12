# Domain 07 States, revisions and provenance

## 1. What this is and why it exists

Three habits repeat in every table, and learning them once makes every model readable: **states** (a row moves through a short
list of named steps, enforced by the database), **revisions** (a counter that stops two editors overwriting each other) and
**provenance** (which model, which run and which policy made a row). They are why the application can be killed at any moment,
edited from two windows, and still explain itself.

## 2. Where it lives

| Habit | Where |
|---|---|
| State lists | `StrEnum` classes in each `models.py`; the database check `enum_check` in `backend/infrastructure/db/types.py` |
| Revisions | `optimistic_locked_update` in `backend/infrastructure/db/optimistic.py`; `StaleRevisionError` in `backend/app/identities/use_cases.py` |
| Provenance | `processing_run_id`, `execution_segment_id`, `runtime_variant_id`, `detector_component_version_id` columns; `calibration_profile_id` on evidence |
| Tests | `tests/concurrency/test_optimistic_concurrency.py`, `tests/integration/test_memory_models.py` |

## 3. How it works

- **States are a closed list** in Python *and* a `CHECK` in the database, so a typo never reaches a row. Moves are *guarded
  transitions*: `UPDATE ... WHERE state = 'RUNNING'`, so a stale actor changes nothing.
- **`PENDING` means private.** A run's output is `PENDING` until acceptance makes it `ACTIVE`; a crash leaves it unseen
  ([acceptance](../processing/04-checkpoints-and-acceptance.md)).
- **`SUPERSEDED` and `DELETED` keep history.** The design is that a re-run supersedes older output rather than erasing it (**not built yet**: today a repeated processing request leaves both generations `ACTIVE`). Only erasure removes
  biometric bytes ([erasure](../../02-data-and-storage/07-erasure.md)).
- **Revision**: new rows start at `1`; every change adds `1`. An update names the revision it saw
  (`expected_revision`); if the row has moved on, zero rows match and the caller gets a conflict (HTTP 409) and re-reads.
  The same idea protects a person's name, an identity merge and a source rename.
- **Provenance chain**: representation → `runtime_variant` (the exact variant that executed, including the provider) →
  export → component version (the model). The detector is recorded on the observation, the embedder on the representation,
  the policy on the run's configuration snapshot ([snapshots](../processing/02-configuration-snapshots.md)).
- **Time**: stored as UTC; the type `UTCDateTime` refuses a time without a zone.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([README](README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select state, revision from sources" "select state, revision from identities" "select count(*), count(runtime_variant_id) from representations"
```

Observed: every source `('ACTIVE', 2)` (import then acceptance); identities with revisions 3 and 4 before any correction
(created, then touched by each accepted face); `(3, 3)`: every representation records which variant made it. Then run the
conflict tests:

```bash
uv run pytest tests/concurrency -q
```

Expected: `18 passed` (observed). Try the stale write by hand with the people routes: rename a person
twice using the same `expected_revision` ([people routes](../api/routes/people.md) shows `409`).

## 5. Change it

To add a state, change the enum **and** write a migration for the check list, then add the transition's guarded update and its
test; an enum value without the migration fails on the first write. This is the same recipe as adding a column.

## 6. Break it on purpose

In a copy of the database, `update sources set state = 'ARCHIVED'`: `CHECK constraint failed` names the table's state check.
The list is closed on purpose.

## 7. Exercises

1. Why does a changed row refuse an update that names an old revision?
2. What does `PENDING` guarantee to a reader of the library?
3. What is the provenance chain of a vector?
4. Why use a guarded `UPDATE ... WHERE state = ...` and not read-then-write?

**Answers**

1. Otherwise a second editor would silently overwrite the first one's change.
2. That its row is private and not yet authoritative: it is not shown or searched.
3. Representation, runtime variant, export, component version.
4. Between the read and the write another actor may have moved the row; the guard makes the move atomic.

## 8. Related files

- Previous: [06](06-occurrences-and-evidence.md) · Up: [Domain](README.md)
- [`backend/infrastructure/db/optimistic.py`](../../../../backend/infrastructure/db/optimistic.py), [transactions](../../02-data-and-storage/03-transactions-and-unit-of-work.md)
