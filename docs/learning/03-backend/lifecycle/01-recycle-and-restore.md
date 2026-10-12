# Lifecycle 01 Recycle and restore

## 1. What this is and why it exists

Mistakes happen, so removal from the library is two-stage. **Recycle** moves a source to the bin; **restore** brings it back.
Both are *logical*: only the source's own row changes. Its files, faces, vectors, evidence and processing history stay exactly as
they were, so restoring needs **no reprocessing**.

## 2. Where it lives

| Thing | Where |
|---|---|
| Use cases | `recycle_source`, `restore_source` in `backend/app/sources/lifecycle.py` |
| Routes | `DELETE /api/v1/sources/{id}` (204), `POST /api/v1/sources/{id}/restore` ([sources routes](../api/routes/sources.md)) |
| Effect on listings and search | the library list and search show active sources by default; the bin is `state=RECYCLED`, and search has an explicit recycled filter (`include`, `exclude`, `only`); memory pages mark faces with `source_recycled` |
| Tests | `tests/integration/test_source_recycle.py`, `test_api_source_lifecycle.py` |

## 3. How it works

- `recycle_source` sets the source `RECYCLED` with `recycled_at`, adds one to its `revision`, and the route passes the revision it just read
  (`expected_revision=source.revision`), so a concurrent change is refused. Restore does the reverse. A repeat of the same request is harmless.
- Faces of a recycled source are filtered by source state in the queries (search offers `include`, `exclude` and `only` for recycled
  sources; memory responses carry `source_recycled`), but nothing is erased and the index is untouched.
- **Processing a recycled source is refused** (`require_processable_image`: the source must be `ACTIVE`).
- Only a `RECYCLED` source can be permanently deleted ([next lesson](02-permanent-delete.md)): the two-step is deliberate.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Continue from the practice library ([domain README](../domain/README.md)); with the
backend running, copy the id of `green.png` from `GET /api/v1/sources` and:

```bash
curl -s -i -X DELETE -H "$H" $B/api/v1/sources/$SID | head -1                       # HTTP/1.1 204 No Content
curl -s -H "$H" "$B/api/v1/sources?state=RECYCLED&limit=10" | j "[i['display_name'] for i in d['items']]"
curl -s -X POST -H "$H" $B/api/v1/sources/$SID/restore | j "d['state']"
```

Observed (through a script doing the same calls): `204`, `['green.png']`, `ACTIVE`. Setup of `$H`, `$B` and `j` is in
[call the API](../api/01-call-the-api.md). Stop the backend and look at the database: only `state`, `recycled_at` and `revision` of
the one `sources` row moved. Tests: `uv run pytest tests/integration/test_source_recycle.py tests/integration/test_api_source_lifecycle.py -q`
(`39 passed`).

## 5. Change it

A "recycle also hides its faces from people counts" rule lives in the query layer, not in recycle. If you want a new place to
hide recycled data, add the filter to the query and a test in the matching routes test file; never copy state into other tables.

## 6. Break it on purpose

Restore twice: the second call answers `200` and nothing changes. Recycling a source that is already recycled
is also harmless to repeat; the tests in `test_source_recycle.py` list each case ([routes lesson](../api/routes/sources.md)).

## 7. Exercises

1. Does recycling delete any file?
2. Why does restore need no reprocessing?
3. Can a source that is still `ACTIVE` be permanently deleted?
4. Which table holds the bin?

**Answers**

1. No; only the source row changes.
2. Everything derived from the picture was kept.
3. No (`SOURCE_NOT_RECYCLED`).
4. `sources` (`state = 'RECYCLED'`).

## 8. Related files

- Next: [02 Permanent delete](02-permanent-delete.md)
- [`backend/app/sources/lifecycle.py`](../../../../backend/app/sources/lifecycle.py)
