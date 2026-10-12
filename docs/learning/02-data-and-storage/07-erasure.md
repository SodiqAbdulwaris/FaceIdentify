# Data 07 Erasure: forgetting a face for real

## 1. What this is and why it exists

A face vector is **biometric data**. When you forget a person or permanently delete a picture, "set a flag" or
"delete the row" is not enough: the vector's bytes may remain inside an older index generation file, in a
quarantined copy, in free pages of the database file, or in the write-ahead log. Erasure is therefore a careful,
multi-step, crash-safe procedure whose job is to make the vector verifiably gone from every place the application
controls, and to say honestly when it could not finish. It is the deepest example of the project's rule that a
claim ("erased") must be true or not made.

## 2. Where it lives

| Thing | Where |
|---|---|
| The procedure | `RepresentationEraser` in `backend/app/memory/erasure.py` (`queue`, `erase`, `resume`) |
| The index side | `IndexCoordinator` (rebuilds a space without the vector; retires old generations) |
| The log side | `truncate_wal` in `backend/infrastructure/db/engine.py`; the `wal_truncation_owed` marker in `app_state` (`backend/app/settings/app_state.py`) |
| Who calls it | `ForgetIdentityUseCase` (`backend/app/identities/forget.py`), permanent source deletion (`backend/app/sources/permanent_delete.py`), startup recovery (`resume`) |
| Tests | `tests/integration/test_representation_erasure.py`, `test_sqlite_erasure_policy.py`, `test_forget_identity.py`, `tests/recovery/test_startup_recovery.py` |

## 3. How it works

The order is the owner's (decisions of 2026-10-01); each step is a *guarded transition*, so any can be repeated:

1. **Queue and exclude** (one transaction). Each `ACTIVE`, `PENDING` or `SUPERSEDED` representation moves to
   **`ERASING`** and, if it has an `ann_key`, a `REMOVE` is queued. From the moment this commits, `ERASING` is
   excluded from retrieval, from candidate revalidation and from every index build. It keeps its vector and key for
   now, so a crash can still be finished.
2. **Apply the removal.** Removing a key from a USearch index and saving it does **not** remove the vector's bytes
   from the saved file (this was probed). So a `REMOVE` for an erasing representation is applied by **rebuilding the
   space's index from SQLite** (which excludes it), once per space for the whole batch. No `REMOVE` is marked
   `APPLIED` while an older generation file remains.
3. **Retire and clear.** Once every needed `REMOVE` is `APPLIED`, no superseded generation file remains and the space's
   quarantined generations are deleted, the representations become **`ERASED`** (vector and key set to `NULL`) in a
   transaction that also sets the durable **`wal_truncation_owed`** marker.
4. **Truncate.** `PRAGMA secure_delete = ON` already zeroes freed pages in the main file, but not the log, so
   `truncate_wal` runs a checkpoint that empties it, **outside any transaction**. Only if that succeeds is the
   marker cleared. A reader holding an old snapshot can prevent it: then the result is "cleanup outstanding", never
   "complete".
5. **Verify.** The cleared rows are read back.

A crash at any point leaves a state startup can finish (`resume` runs the same steps for everything still `ERASING`
and truncates the log if the marker is set). A space whose cleanup cannot finish (a locked file on Windows) is
**reported and left `ERASING`**, without stopping other spaces. The HTTP answer reflects it: `204` when everything is
gone, `202` with what is outstanding otherwise, and `/readiness` shows `recovery: DEGRADED` until the next start.

> "Erased" means the vector is gone from SQLite, the index files and the log **as far as the application can
> verify**. It is verified file deletion, not a claim of physical erasure from SSD storage, snapshots or backups.

What stays after a forget: the media (the picture), the Person and their **name**, and Evidence (detached from the
deleted vectors). What goes: the vectors and keys. See [forget](../03-backend/lifecycle/03-forget.md).

## 4. Try it

**Works with no models. Verified 2026-10-12** on a fresh scratch library with at least two identities (start-here
lesson 07). With the backend running, pick the identity of the *green* picture (find it through
`GET /api/v1/sources/{id}/occurrences`), note its `revision`, and forget it:

```bash
curl -s -i -X POST -H "$H" -H "Content-Type: application/json" \
  -d "{\"expected_revision\":$REV}" $B/api/v1/identities/$GID/forget
```

Expected: `HTTP/1.1 204 No Content`. Then:

1. `GET /api/v1/identities/$GID` is now `404 IDENTITY_NOT_FOUND` (a forgotten identity is not visible); the
   occurrences of its source are an empty list; repeating the forget answers `204` again (a repeat is harmless).
2. Read the database (read-only):

   ```python
   import sqlite3, pathlib
   con = sqlite3.connect(f"file:{pathlib.Path.home()}/faceidentify-play/lib/database/library.db?mode=ro", uri=True)
   q = lambda s: [tuple(r) for r in con.execute(s)]
   print(q("select state, vector is null, ann_key is null from representations order by created_at"))
   print(q("select state, count(*) from identities group by state"))
   print(q("select operation, state, count(*) from index_operations group by 1, 2"))
   print(q("select kind from evidence where kind like '%FORGOTTEN%'"))
   print(q("select key from app_state"))
   ```

   Observed: the representation list contains exactly one `('ERASED', 1, 1)` (vector and key are `NULL`) among the
   `('ACTIVE', 0, 0)` ones; identities `[('ACTIVE', 1), ('FORGOTTEN', 1)]`; index operations
   `[('ADD', 'APPLIED', 6), ('REMOVE', 'APPLIED', 1)]` (the `REMOVE` was applied, by a rebuild); evidence
   `[('IDENTITY_FORGOTTEN',)]`; and `app_state` holds only `library_profile`: **no `wal_truncation_owed` marker is
   left**, because the truncation succeeded.
3. The index shrank: `cat state/indexes/*/manifest.json` shows `"count"` one lower than before (5 instead of 6 in the
   verified run), and only the new generation file remains.
4. Search with the forgotten picture (`POST /api/v1/search/face`): it no longer finds that identity (observed
   `POSSIBLE_PEOPLE NOT_SIMILAR [0.208]`, the only remaining identity).
5. Run the tests (platform note: two tests that need Windows file locks fail on Linux):
   `uv run pytest tests/integration/test_forget_identity.py tests/integration/test_sqlite_erasure_policy.py -q`.
   `test_sqlite_erasure_policy.py` searches the database file's bytes for the erased vector.

## 5. Change it

The safe change is to *read*, not alter, the erasure code: open `backend/app/memory/erasure.py`, find `ERASABLE`
(`ACTIVE`, `PENDING`, `SUPERSEDED`) and the report dataclass `ErasureReport` (`erased`, `pending`, `ignored`,
`blocked`). The decisions it encodes are the owner's and are in `docs/implementations/2026-10-01-decide-q25-q26-erasure-and-recovery.md`
and `.agents/CONTEXT.md` (open questions 25 and 30). To add a new reason to erase (a new feature), do not touch
the procedure; call `RepresentationEraser.erase(ids)` from your use case after your own transaction, as
`forget.py` does, and add a test in the style of `test_forget_identity.py`.

## 6. Break it on purpose

Hold a reader open so the log cannot be truncated. In a Python session open a connection to your library and
begin a read that stays open (`con.execute("begin"); con.execute("select * from sources").fetchall()` without
finishing), then forget an identity through the API. Expected: the call answers `202` with an `outstanding` list
(not `204`), `/readiness` says `recovery: DEGRADED`, and the marker `wal_truncation_owed` stays in `app_state`;
closing your connection and restarting the backend lets `resume` finish it. (This is the documented behaviour
of `truncate_wal`, which "returns False when a reader blocks it"; the tests `test_startup_recovery.py::test_an_erasure_that_cannot_finish_is_reported_unresolved_not_clean`
and `test_sqlite_erasure_policy.py` pin it. The by-hand run was not repeated.)

## 7. Exercises

1. Why does a `REMOVE` for an erasing vector rebuild the index instead of removing the key in place?
2. What does `ERASING` mean and why does it exist before `ERASED`?
3. What is the `wal_truncation_owed` marker for?
4. After forgetting a person, what is still in the library?
5. Why is the claim "securely retired" limited to verified file deletion?

**Answers**

1. A saved USearch generation still holds a removed key's bytes; only a rebuilt generation without the vector (and
   no older file) removes them.
2. It excludes the vector from every use at once while keeping it so a crash can finish the job; `ERASED` is the end.
3. It records that the log must still be truncated, so a crash between clearing the vector and truncating is
   recoverable; it is cleared only after a successful truncation.
4. The picture, the person's name (if named), Evidence detached from the deleted vectors, but no vectors.
5. The application cannot see inside an SSD's wear levelling, snapshots or backups; it claims only what it verified.

## 8. Related files

- Previous: [06 The vector index and the outbox](06-vector-index-and-outbox.md) · Next: [08 Storage roots and artifacts](08-storage-roots-and-artifacts.md)
- [`backend/app/memory/erasure.py`](../../../backend/app/memory/erasure.py)
- [Forget](../03-backend/lifecycle/03-forget.md), [permanent delete](../03-backend/lifecycle/02-permanent-delete.md)
- [`docs/implementations/2026-10-01-m2-representation-erasure.md`](../../implementations/2026-10-01-m2-representation-erasure.md)
