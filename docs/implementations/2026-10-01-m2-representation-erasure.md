# M2: representation erasure (single and bulk), the owed-truncation marker and erasure recovery

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 · TST-031 (INDEX-03, INDEX-04, INDEX-05, PER-07, PER-08), TST-032 (revision 0004); GitHub issues #29, #52
- **Status:** done for representation-level erasure; the Source/Recycle-Bin deletion and identity-level forget parts of TST-031 are not built
- **Commits:** PR (this branch `feat/representation-erasure`): `feat(db): app_state table for the WAL-truncation-owed marker`, `feat(memory): erasing REMOVEs rebuild the index and wait for retirement`, `feat(indexing): list superseded files and retire quarantined generations`, `feat(memory): two-step representation erasure, single and bulk`, `feat(recovery): finish interrupted erasures at startup`

## What changed

- **Revision `0004_app_state`** and `AppState` (`backend/app/settings/models.py`): a key/value table
  `app_state(key PK CHECK(key != ''), value, updated_at)`. `AppStateRepository`
  (`backend/app/settings/app_state.py`) has `set` (one upsert), `get` and `clear(key, value=None)` (a compare-and-delete:
  a marker set again meanwhile survives an earlier checkpoint). The only key so far is `wal_truncation_owed`.
- **`IndexCoordinator`** (`backend/app/memory/index_coordinator.py`): the `REMOVE` of an `ERASING` representation (or one
  with no key) is applied by rebuilding the space's index from SQLite (the purge path), which excludes it; all
  `REMOVE`s of a space in a pass share that one rebuild. An ordinary `REMOVE` stays in place. **No `REMOVE` is marked
  `APPLIED` while a superseded generation file remains** (`_require_retired`; a failing `REMOVE` is retried with backoff;
  an `ADD` of the same pass is unaffected). `exclusive()` exposes the coordinator's lock so finalization cannot race a pass.
- **Index helpers** (`representation_index.py`): `superseded_files(directory)` (a fresh listing against the manifest on disk
  now) and `retire_quarantine(directory)` (deletes the index's own quarantined files, never through a link, and returns what
  a second listing still finds).
- **`RepresentationEraser`** (`backend/app/memory/erasure.py`): `erase(ids)` and `resume()`. Order: `queue` (one
  transaction: guarded `ACTIVE`/`PENDING`/`SUPERSEDED` -> `ERASING`, a `REMOVE` for those with a key, and a `REMOVE` for any
  `ERASING` one that has none) -> one coordinator pass sized to the pending queue -> per space, under the coordinator's
  lock: a representation with a key is ready when a `REMOVE` is `APPLIED` and none is `PENDING`/`FAILED`, a keyless one
  always; for keyed ones a fresh listing must show no superseded file and the quarantine must be deleted; then one
  transaction sets the marker and clears vector and key (`ERASED`, guarded by `state = 'ERASING'`) -> `truncate_wal`
  (outside any transaction; the marker is cleared only if it still holds the value read before the checkpoint) -> read the
  cleared rows back. `ErasureReport.complete` is false while anything is owed (blocked space, index errors, representations
  still erasing, a failed verification, a log not truncated). A space failing with any exception is reported and the others
  proceed.
- **Startup recovery** (`backend/app/recovery/startup.py`): `recover_on_startup` takes the eraser (required), calls `resume()`
  after validating indexes and requeueing failed operations, and `StartupReport.erasure` feeds `unresolved` and
  `repaired_nothing`.

## Why

PERSISTENCE_IMPLEMENTATION §6.2 (decision 2026-10-01, open question 25), §23 and §25 (open question 30, issue 52), and the
tests INDEX-03/04/05 and PER-07/08 of TESTING_STRATEGY.

## Decisions

- **Owner, this session:** the marker is a key/value table (revision 0004 contains it only; #55 stays optional and unbuilt);
  `erase_representations` is representation-scoped and writes **no Evidence** (`IDENTITY_FORGOTTEN` belongs to the later
  identity-level forget); `ACTIVE`, `PENDING` and `SUPERSEDED` may move to `ERASING` and a representation without an
  `ann_key` bypasses the index work; per-space failure isolation and keeping failed representations `ERASING` for recovery.
- **Finding, not yet owner-approved (issue opened):** persistence §6.2 item 2 says step two "needs no rebuild for a single
  erasure". A probe (`usearch` 2.x, 16 dimensions) shows a generation saved after `remove()` still contains the removed
  vector's bytes, and one rebuilt without it does not. So the `REMOVE` of an `ERASING` representation rebuilds the space.
  A pinned test (`test_an_ordinary_remove_is_applied_in_place_and_leaves_the_bytes_in_the_saved_file`) fails if USearch
  changes that. The cost is O(vectors in the space) per erasure pass.
- The clearing transaction's marker value is a fresh id per call, so concurrent erasures cannot clear each other's marker.
- Clearing the marker after the truncation writes one frame to the log; it holds no vector, and the test asserts the
  vector bytes are absent from the database file and the log rather than that the log is empty.
- Not a guarantee of physical erasure (SSD wear levelling, snapshots, backups).

## Verification

- `uv run ruff format --check .` (120 files formatted), `uv run ruff check .` (clean), `uv run mypy` and
  `uv run mypy --platform linux` (no issues in 120 files), `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 987 passed,
  backend coverage 100% (statements and branches).
- New tests: `test_representation_erasure.py` (34; INDEX-03/04/05, PER-07 at five crash points, PER-08 by byte search of the
  database file, its log and every file under the index directory, run five times without a failure), `test_migration_0004.py`
  (7), 10 index-helper tests, 5 coordinator tests, 3 startup-recovery tests plus the report-property cases.
- Mutations, each broken, shown to fail a test and restored byte-identical: coordinator (3), index helpers (9, one equivalent
  mutant deleted rather than tested), eraser (13), startup wiring (4). Two early "kills" were discarded because the test file
  did not parse or the mutant raised `NameError`, and redone.
- **Not verified:** a real SSD/snapshot; two processes erasing at once (the library lock is open question 23); a concurrent
  reader holding the log across a real application session.

## Review

Independent read-only review by an Explore subagent in a disposable worktree (Codex was over its usage limit until
2026-10-03); posted on PR 58. Findings and what was done:

- **B1 (blocker, fixed):** an ordinary `REMOVE` in flight when the erasure was queued made the erasure skip its own
  (the unique pending `REMOVE`), leaving the vector in the live index file. `queue` now deletes a pending `REMOVE` of
  each representation it moves and appends a fresh one (applied by a rebuild); the late settlement of the deleted one is
  skipped. Test reproduces it from inside a coordinator pass.
- **M1 (fixed):** `erase()` could report complete while another eraser's truncation was owed. The states are now read
  before the marker.
- **M2 (fixed):** a `FAILED` `REMOVE` of an `ERASING` representation is requeued by `queue`.
- **m1 (fixed):** `resume` reports an unexpected exception instead of aborting startup. **m2 (fixed):** only the
  erasing representations' operations count as errors. **m4 (fixed):** the marker token is `uuid.uuid4()`.
- **m3 (answered):** a cleared row has no key, so candidate revalidation cannot return it; the bytes in the index
  files are covered by the rebuild and the byte-search tests, not by `_verify`.
- **n1 (answered):** the erasure code and its tests are one logical unit in one commit; it is above the guide's ~400 lines
  for that reason. **n2 (done):** comment added. **n3 (answered):** the unapproved finding is labelled as such in the note.

## Open issues / follow-ups

- Confirm the "no rebuild for a single erasure" correction (issue).
- The remaining TST-031 scope: Source deletion, Recycle Bin cleanup and identity-level forget (they call this use case).
- `ErasureReport.erased` for `erase()` includes ids that were already `ERASED`; documented in the report.
- `checkpoint_timeout_ms` is a constructor argument so tests do not wait 5 s; production uses the default.
