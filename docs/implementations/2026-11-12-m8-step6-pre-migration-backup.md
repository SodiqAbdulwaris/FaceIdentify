# M8 step 6, first part: a copy of the database before an upgrade

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M8 step 6 (decision R9) · TST-081 (not `PASSING`: the installer upgrade test is not built)
- **Status:** done
- **Commits:** PR #253: `feat(db): copy the database before upgrading a library`, `docs(m8): record the pre-migration database copy`, and the review fixes

## Why

M8 decision R9: an upgrade of a library is the one step that can damage the owner's data, and the
installer upgrades in place, so the database is copied first and the copy kept (last three), as step 6
of [the M8 plan](../plans/M8_PLAN.md) requires.

## What changed

- `backend/app/lifecycle.py`: `migrate` now takes `backups` and `clock`. When the database is stamped with
  an older, known revision (not the head), it is copied with SQLite's online backup into
  `<library>/backups/pre-migration-<revision>-<UTC time>.db` before Alembic runs. The copy is written
  under a `.partial` name and renamed, so a half-written copy never carries a backup's name, and the
  newest three (`BACKUPS_KEPT`) are kept. A copy that cannot be made raises and the upgrade does not
  start, so the library stays as it was. A new library, one already at head, a newer one and a foreign
  one make no copy (the last two were already refused untouched).
- `tests/integration/test_library_lifecycle.py`: four tests (a populated `0010` library, the previous
  release, opens through `open_library`: the copy is exact and every row is kept at the head revision; none at head
  or when new; only three kept; a failed copy stops the upgrade and releases the lock) and two existing
  helpers adapted to the new `migrate` signature (no assertion changed).

## Verification

- Library lifecycle, API lifespan, downgrade-guard and migration tests: 91 passed locally.
- The full local backend run had 85 failures and 29 errors that are not this change: the video tests need
  the pinned FFmpeg (not installed on this machine; CI installs it) and a shared-memory name collision
  with another session's run. CI runs the full gate on the exact head; see the PR.

## Decisions (delegated, 2026-11-12; the owner may reverse any)

- The backup lives in the library's existing `backups/` folder (so it travels with the library) and is
  named by the revision it holds, then the time, so a restore picks the file by the schema it needs.
- Indexes are not copied (rebuildable, R9).

## Open issues / follow-ups

- Restoring a copy is manual (close the app, copy the file over `database\library.db`, delete its `-wal` and `-shm`). A guided restore is not built.
- Step 6's installer-level upgrade and uninstall tests belong with the CI installer job (step 7).
