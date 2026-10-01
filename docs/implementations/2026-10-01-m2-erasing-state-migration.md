# M2: the ERASING state and the second Alembic revision

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-032, TST-031 part); resolves the Q18 half of GitHub issue #35 and
  the schema step of #29
- **Status:** done; the erasure use case and the rest of TST-031 are not built (issue #29); the downgrade
  policy, Q19, stays open (issue #35)
- **Commits:** [PR 47](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/47): `feat(db): add the ERASING
  representation state`, `test(db): migrate a populated database to the ERASING state`, `docs: record the
  ERASING migration` (review fixes are folded in; see Review)

## What changed

- `RepresentationState.ERASING` (`backend/app/memory/models.py`) and revision
  `backend/alembic/versions/0002_representation_erasing_state.py`, which replaces the `state` CHECK of
  `representations`. `ERASING` keeps its vector and key, so the `erasure` and `active_eligible` CHECKs are
  unchanged. Nothing else in the schema changes.
- `backend/alembic/env.py`: migrations now run with foreign key enforcement off and check
  `PRAGMA foreign_key_check` inside each revision's transaction, before it commits (the decision note
  is in persistence §27).
- `tests/integration/test_migration_0002.py` (11 tests); `test_migrations.py` and `test_memory_models.py`
  updated for the new head and value set.

## Why

The owner decided erasure is two-step (PR 42), with `ERASING` as the durable marker, and deferred Q18 to
"the second Alembic revision". Q18 asked for a populated-database upgrade test and to check that
recreating a table with foreign keys on behaves. It does not.

## The finding: a plain batch recreation fails on a populated database

Recreating `representations` (SQLite cannot alter a CHECK in place) drops it, and `index_operations` and
others reference it. Run against a database holding even one referencing row, the upgrade failed with
`FOREIGN KEY constraint failed` on `DROP TABLE representations`. An empty database never shows it, which is
why every earlier test passed. The failure was atomic (still at `0001`, data intact), so the old failure test
stood, but no revision of this kind could ever have been applied to a real library.

SQLite's documented procedure is the fix: foreign keys off *outside* the transaction (the pragma does
nothing inside one), recreate, `PRAGMA foreign_key_check`, commit. `env.py` does that on the migration's own
connection.

## Decisions

- **The check runs in `on_version_apply`, not after `run_migrations()`.** My first version ran it after,
  and a test caught that it did nothing: SQLite gives Alembic no transactional DDL, so **each revision is
  its own transaction** and was already committed by then, along with its version stamp. A raise there left
  the database at `0002` with the table recreated. `on_version_apply` is called inside the revision's
  transaction after its statements and stamp, so a violation rolls that revision back. It also means a
  failing second revision leaves `0001` applied, which is the shape Q18 asked to prove.
- **A database that was already inconsistent is refused**, not upgraded: `foreign_key_check` reports every
  violation, not only new ones. Foreign keys are mandatory (persistence §25), so this is the safe reading;
  tested.
- **The table is passed as a frozen definition (`copy_from`), not reflected.** Reflection made
  `upgrade --sql` fail ("batch mode ... requires a live database"), breaking the documented way to review a
  migration's SQL. The frozen copy is the `0001` table, with five stub parent tables so the foreign keys
  can be rendered. It must keep matching `0001` and the model; the existing tests that compare the migrated
  schema, indexes and constraints with `create_all` (and `alembic check`) fail if it drifts (mutation-checked).
- **Foreign keys are not turned back on.** The migration's connection is private and disposed straight
  after, so the re-enable was dead code and was deleted; the application's own connections enforce as before
  (tested).
- **Downgrade:** restores the old CHECK and keeps every row when nothing is `ERASING`; refused atomically by
  the database while any representation is (the old schema cannot hold the state). That is a fact about this
  revision, not a decision on Q19, which stays open.
- **Not changed:** the coordinator and recognition. They already treat only `ACTIVE` as eligible, so an
  `ERASING` representation is excluded from index builds today without code (the recognition-side
  revalidation is issue #44).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 849 passed (11 new, 0 regressions in the 838 before);
  `backend/` coverage 100%. The migration tests were run 5 times in a row: 22 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 16 (foreign keys not disabled or disabled
  wrongly, the hook not registered, the violation test and the check itself removed; the new state missing,
  the old set wrong, either direction of the revision removed; an index, a unique constraint, a CHECK and an
  `ON DELETE` rule altered in the frozen table; forcing one transaction for the whole run, and the
  message's text and its rowid), all caught. Two of the three added after review survived at first (the
  one-transaction claim had no test that could tell; the rowid in the message was not asserted).
- **Not verified:** a very large library (the recreation copies the table inside one transaction; persistence
  §27 rule 5 asks for separate steps on large tables, and `representations` can be the largest).

## Review

Codex was over its usage limit again, so the independent review was a read-only subagent (an approved
reviewer) in a disposable worktree: request changes. It confirmed the core procedure sound (the pragma is
effective, `on_version_apply` runs inside each revision's transaction for upgrade and downgrade, the frozen
table matches `0001`, `ERASING` interacts correctly with the other CHECKs and code).

| Finding | Resolution |
|---|---|
| The first commit left the repository failing its tests (the head and value-set assertions changed in the next commit) | Fixed: the branch was rebuilt so the two one-line test updates are in the feature commit |
| "Each revision is its own transaction" was claimed but no test could tell it from one big transaction: every rollback test migrated to `0001` in a separate command first | Fixed: a test runs one `upgrade head` from an empty database with `0002` failing and shows `0001` stays applied. Forcing a single transaction in `env.py` now fails it (mutation-checked) |
| `patch_upgrade` only wrapped `upgrade`; downgrade's enforcement and check were implied, not asserted | Fixed: the helper wraps both; a test records enforcement during a downgrade and another shows a downgrade that leaves a dangling reference is rolled back |
| Stale note in persistence §6.2 (said the schema change comes "with the deletion work") | Fixed: it says revision `0002` (done) |
| `upgrade --sql` output lacks the pragma and the check, so replaying it by hand would fail | Documented in `env.py` and the Alembic README: the output is for review only |
| The violation message did not say which row, or that it may pre-date the migration | The message now names the first offending table, rowid and parent, and says the database may have been inconsistent before; tested |

## Open issues / follow-ups

- Issue #29: the erasure use case, coordinator retirement of old generations, recovery of `ERASING`, and
  INDEX-03, INDEX-04, INDEX-05, PER-07.
- Issue #35: Q19 (downgrade policy) remains.
- Rule 5 for large tables: if `representations` grows large enough for the recreation to matter, this
  revision's approach (recreate in one transaction) is the thing to revisit.
