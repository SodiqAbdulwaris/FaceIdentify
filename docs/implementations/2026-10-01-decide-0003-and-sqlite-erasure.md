# Decide revision 0003 (ann_key scope, snapshot triggers) and the SQLite erasure policy

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-031, TST-032); decisions and one correction, no schema or behaviour
  change
- **Status:** done (documents); the implementation is tracked in GitHub issues #48, #51, #52 and #29
- **Commits:** [PR 53](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/53): `docs(specs): decide ann_key
  scope, snapshot triggers, SQLite erasure`, `fix(processing): correct the claim that snapshots may be shared`,
  `docs: record the revision 0003 and SQLite erasure decisions` (review fixes are folded in; see Review)

## What was decided (owner, 2026-10-01)

1. **#48: an `ann_key` is unique within its space**, `UNIQUE(representation_space_id, ann_key)`, instead of
   across the whole table. Every index lookup and removal carries the space and the key. The allocation policy
   is unchanged (a permanent key only when a representation becomes ANN-eligible; run-local indexes keep
   ephemeral labels). Revision `0003` recreates `representations`, keeps every key and verifies the new
   uniqueness. Spec: persistence 6.2, 6.3.
2. **#51: snapshots are immutable and one per run, enforced by the database.** Two triggers (`UPDATE` always
   aborts; `DELETE` aborts while a run references the snapshot) in revision `0003`. Snapshots carry every value
   needed to reproduce a run, never references to mutable rows. Spec: persistence 13.
3. **#31: `PRAGMA secure_delete = ON` on every connection, and a `wal_checkpoint(TRUNCATE)` after each erasure
   batch commits**, retried if readers prevent it, with the erasure reported as having outstanding cleanup until
   it succeeds. Not a guarantee of physical erasure. Spec: persistence 25 and 6.2 (items 9-10).
4. Q17, Q19, Q20, Q21, Q23, Q24 and Q27 stay as previously agreed.

Test requirements added to `docs/strategy/TESTING_STRATEGY.md`: **PER-08** (no residue in SQLite after an
erasure), **PER-09** (snapshots immutable and one per run), **PER-10** (ann keys unique per space). TST-031 and
TST-032 in the tracker carry them. CONTEXT questions 28, 29 and 30 record the decisions.

## Where I interpreted, and one thing I got wrong

- **"Unique constraint on the snapshot's `run_id`"** does not match the schema: a snapshot has no run column;
  the run holds the foreign key (`processing_runs.configuration_snapshot_id`). The same invariant is a unique
  constraint on that column, and **it already exists** (`uq_processing_runs_configuration_snapshot_id`, in the
  model and in `0001`). So revision `0003` needs only the triggers for #51.
- **My error, corrected here.** In PR 50 I wrote, in the repository's module docstring, its tests, its
  entry, the tracker and issue #51, that the database did *not* enforce one snapshot per run because
  `configuration_snapshot_id` "is not unique". I had not looked at the schema; it is unique. The review comment I
  "corrected" in response was right. A test now shows a second run on the same snapshot is refused, and every
  place that said otherwise is fixed (module docstring, tests, the entry with a dated correction, the tracker
  row, issue #51).
- **Run deletion and snapshots (the owner asked me to decide).** Deleting a run **retains its snapshot** as
  historical evidence. The `DELETE` trigger aborts while a run references the snapshot (the foreign key says so
  too; the trigger gives a clear message) and allows deleting one no run references, so permanent deletion of a
  Source, an explicit lifecycle operation, deletes its runs and then their now-unreferenced snapshots. The
  database cannot tell that operation from any other caller (the trigger allows deleting any unreferenced
  snapshot), so "only the lifecycle removes a snapshot" is the application's rule, not a database guarantee. This is slightly narrower than "reject deletions of committed snapshots" and
  is flagged for the owner to confirm with the deletion work (TST-031). Ordinary updates stay prohibited either
  way.
- **The erasure sequence** merges the owner's with the design approved for Q25. The owner listed "delete the
  relevant SQLite records" and then retiring index generations; Q25 requires the superseded generations to be
  retired *before* the vector is cleared (so a `REMOVE` is never reported applied while an old generation holds
  the vector). I read "delete the SQLite records" as clearing the vector and key (`ERASED` keeps its
  provenance, persistence 6.2) and kept Q25's order: queue and exclude; apply the index removal or publish a
  replacement generation; retire old and quarantined generations; clear the vector and key and commit;
  checkpoint; verify. The checkpoint is a privacy mechanism for erasure, which persistence 25 had called "an
  optimization, not a correctness mechanism"; the note says so.
- **A checkpoint that cannot finish needs a durable record** (the review's critical finding; my first draft
  said it did not, and was wrong). The checkpoint is idempotent and the log database-wide, so it can be retried
  at the next erasure batch, startup or maintenance; but `ERASED` is committed before the checkpoint, so after a
  crash between them the database could not say the cleanup is owed, and "not complete until the checkpoint
  succeeded" could not be kept. The specs now require a database-wide "WAL truncation owed" marker, set in the
  transaction that clears the vector and cleared only after a successful truncation; startup runs the
  checkpoint whenever it is set. **The mechanism (a one-row settings value or a column) is a schema/data choice
  for the owner to confirm** when the policy is built (issue #52).

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes, five
findings, all correct.

| Finding | Resolution |
|---|---|
| Critical: erasure cannot durably report or recover a blocked checkpoint (`ERASED` commits first; the record said no marker is needed) | Confirmed; the claim was wrong. The specs now require a durable database-wide "WAL truncation owed" marker (mechanism to confirm with the owner, issue #52), and PER-08 adds the crash-between case |
| The snapshot-deletion policy ("only way") contradicts a trigger that allows deleting any unreferenced snapshot | Confirmed: it is the application's rule, not a database guarantee, and the specs and this entry now say so |
| The spec said revision `0003` was delivered when it is not | Fixed: future tense, and the §6.2 row says the table-wide constraint is still in force until it lands |
| The ann-key decision was not propagated (§21 index list still said unique `ann_key`; CONTEXT still listed the conflict as open; the earlier entry said "not fixed") | Fixed in all three. CONTEXT already had this conflict as **question 13** ("decide before M3"), which I had re-found as question 28: 13 is now resolved and 28 links it |
| Verification counts conflicted (tracker 906 vs 907; 36 vs 37 tests) | Fixed to the verified 907 and 37 |

## Implementation order (the owner's)

1. This PR: document #48, #51, #31.
2. Revision `0003`: the composite unique constraint and the snapshot triggers.
3. Migration tests on populated databases, including a failing upgrade and a downgrade.
4. The SQLite erasure policy (issue #52), then the erasure use case (issue #29).
5. The remaining repository and lifecycle work.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform linux`:
  clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 907 passed (one new test: the second run is refused; 0
  regressions in the 906 before); `backend/` coverage 100%.
- No schema or behaviour changed.

## Open issues / follow-ups

- #48 and #51: open until revision `0003` is merged. #52: the SQLite erasure policy. #29: the erasure use case.
- To confirm with the owner when TST-031 starts: a deleted run keeps its snapshot, and an unreferenced snapshot
  may be deleted by the Source-deletion lifecycle.
