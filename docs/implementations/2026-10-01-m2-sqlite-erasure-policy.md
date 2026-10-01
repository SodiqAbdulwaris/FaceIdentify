# M2: SQLite erasure policy (secure_delete and checkpoint)

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-031 precondition; PER-08); GitHub issues #31 (decided), #52
- **Status:** partial: the pragma and the checkpoint helper are built; the owed marker and the erasure use case are not
- **Commits:** branch `feat/sqlite-erasure-policy`

## What changed

- `PRAGMA secure_delete = ON` is in `SQLITE_PRAGMAS`, so every connection zeroes deleted content in the database file.
- `truncate_wal(engine, *, busy_timeout_ms=5000)` in `backend/infrastructure/db/engine.py` runs
  `PRAGMA wal_checkpoint(TRUNCATE)` on an AUTOCOMMIT connection (outside any transaction) and returns False when a
  reader blocks it, so the caller can report outstanding cleanup and retry.
- `tests/integration/test_sqlite_erasure_policy.py`: a 256-byte marker is stored, deleted and checkpointed; it is in the
  log before the truncation and in neither the database file nor the log after; and a reader holding an older snapshot
  makes `truncate_wal` return False and leave the log, until the reader ends. The pragma test also asserts it.

## Decisions and findings

- With `secure_delete` on, the delete's own log frame holds a zeroed page; the old content stays in the log only in the
  *earlier* frame of the insert, which is why the test erases without checkpointing in between.
- The timeout is a parameter so the blocked case is tested in milliseconds, not the 5 s default.
- **Not built, needs the owner:** the durable "WAL truncation owed" marker. I propose a one-row key/value entry in a
  settings table (a new revision 0004), set in the clearing transaction and cleared after a successful truncation.
  Until then nothing calls `truncate_wal`, so no erasure can wrongly report completion.
- Neither measure guarantees physical erasure (SSD wear levelling, snapshots, backups).

## Verification

- Full gate (see PR); mutations, each restored: removing the pragma (2 tests fail), `PASSIVE` instead of `TRUNCATE`
  (2 fail), always returning True (the blocked test fails).
- **Not verified:** behaviour on a real SSD/filesystem snapshot; concurrent checkpoint from several processes.

## Open issues / follow-ups

- #52 stays open for the marker and the use case that calls the checkpoint (#29).
