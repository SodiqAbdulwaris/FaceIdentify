# Lifecycle 02 Permanent delete

## 1. What this is and why it exists

"Delete Media removes media and evidence-bearing biometric material; it does not remove the people the user named." Permanent
delete is the irreversible removal of one picture: its bytes, every face vector made from it, its observations and processing
runs. It is designed so that a crash at any point is *finished*, not left half done, and so that **the user's own files are never
touched** when a picture was only referenced.

## 2. Where it lives

| Thing | Where |
|---|---|
| The use case (`PermanentSourceDeletion`, `resume`) | `backend/app/sources/permanent_delete.py` |
| Erasing vectors | `RepresentationEraser` in `backend/app/memory/erasure.py` ([erasure lesson](../../02-data-and-storage/07-erasure.md)) |
| The route | `POST /api/v1/sources/{id}/permanent-delete` (204, or 202 when work is still owed) |
| Resuming after a crash | `Backend._open` calls `resume` before any request ([host lesson](../architecture/03-host-and-startup.md)) |
| Tests | `tests/integration/test_permanent_source_delete.py`, `test_api_source_permanent_delete.py` (51 together), `tests/recovery/` |

## 3. How it works

The order is fixed, durable intent first:

1. **Intent** (one transaction): the source moves `RECYCLED` → `DELETING`; every managed artifact it owns (original, thumbnail,
   each face crop) gets a deletion intent. A *referenced* original is only marked `DELETED`: the file is never touched.
2. **Bytes**: each artifact's bytes are removed and its row finalised (`DELETE_FAILED` is retried at the next start).
3. **Representations**: every vector of the source goes through the eraser: the row, the index files and the write-ahead log.
4. **Finalisation** (one transaction, only once 2 and 3 are done): the source's occurrences, observations, representations,
   index operations and processing runs, then their unreferenced configuration snapshots, are deleted. **Evidence that cited
   them is kept** but loses its links to the deleted representations and run (ids, kinds and scores stay; no biometric payload).
   An unnamed identity left with nothing becomes `DELETED`. The source row stays as a **tombstone** (`DELETED`, no name, no media
   facts) so retained evidence still resolves it; a `SOURCE_PERMANENTLY_DELETED` evidence row records that it happened.

Each step can be repeated, so `resume` finishes whatever a crash interrupted. If something cannot finish (a file locked by another
program) the route answers `202` and `/readiness` reports recovery `DEGRADED` until it does.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On a **copy** of the practice library (never your only copy): with the backend
running, recycle then permanently delete `green.png`:

```bash
curl -s -X POST -H "$H" $B/api/v1/sources/$SID/permanent-delete    # on an ACTIVE source: SOURCE_NOT_RECYCLED
curl -s -i -X DELETE -H "$H" $B/api/v1/sources/$SID | head -1       # 204
curl -s -i -X POST -H "$H" $B/api/v1/sources/$SID/permanent-delete | head -1   # 204
curl -s -i -H "$H" $B/api/v1/sources/$SID | head -1                 # 404
```

Observed (same calls from a script): `204`, `204`, then `404`; `/readiness` stayed `READY`. Stop the backend and read the database:

```bash
uv run python q.py <library> "select display_name, state, width, revision from sources" "select kind, state from artifacts where kind = 'SOURCE_ORIGINAL'" "select kind, count(*), sum(source_id is null), sum(processing_run_id is null) from evidence group by 1"
ls <library>/originals
```

Observed: the source row is `('Deleted image', 'DELETED', None, 7)`, a tombstone with no name or size; its artifact is `DELETED` and
`originals/` holds two files instead of three; the processing run and snapshot counts dropped from 3 to 2; evidence
`IDENTITY_CREATED` kept both rows but one now has `processing_run_id` empty (its run was deleted); a new
`SOURCE_PERMANENTLY_DELETED` evidence row exists. Tests: `uv run pytest tests/integration/test_permanent_source_delete.py tests/integration/test_api_source_permanent_delete.py -q` (`51 passed`, about 26 s).

## 5. Change it

Adding something the source owns (a new derived file) means adding it to the **intent** step (so its bytes are deleted), to the
finalisation (its rows), to `artifact_references` (so cleanup never deletes a referenced file), and to the delete test. The
crash tests in `tests/recovery/` show how to prove each step can be interrupted and finished.

## 6. Break it on purpose

Call permanent delete on an `ACTIVE` source: `409 SOURCE_NOT_RECYCLED` ("Move the source to the recycle bin before deleting it."),
nothing changes. That refusal is the safety rail, observed in the [sources routes lesson](../api/routes/sources.md).

## 7. Exercises

1. Why must the source be in the bin first?
2. What is kept of the evidence that cited the deleted faces?
3. What does the user's referenced original suffer?
4. What does `202` mean?

**Answers**

1. A mistake should cost a click (restore), not data; permanent delete is deliberately a second step.
2. Ids, kinds and scores; the links to deleted representations and the run are cleared; no biometric payload.
3. Nothing: only the library's record of it is removed.
4. Some physical cleanup is still owed (for example a locked file); recovery finishes it and `/readiness` shows `DEGRADED` meanwhile.

## 8. Related files

- Previous: [01](01-recycle-and-restore.md) · Next: [03 Forget](03-forget.md)
- [`backend/app/sources/permanent_delete.py`](../../../../../backend/app/sources/permanent_delete.py), [storage cleanup](../../02-data-and-storage/08-storage-roots-and-artifacts.md)
