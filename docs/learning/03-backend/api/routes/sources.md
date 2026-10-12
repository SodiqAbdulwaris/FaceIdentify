# Routes: sources (`backend/api/routes/sources.py`)

## 1. What this is and why it exists

A **Source** is something you imported (today, a still image). This module is how a picture gets into the library,
how the library is listed and read, how the original is served back to the screen, and how a picture is taken out
again: put in the **recycle bin**, **restored**, or **deleted for good**. Importing is deliberately separate from
processing: `import` creates the Source and does not recognise anything.

## 2. Where it lives

| Route | Use case or repository |
|---|---|
| `POST /api/v1/sources/import` | `ImportSourceUseCase` (`backend/app/sources/import_source.py`): `import_managed`, `import_referenced` |
| `GET /api/v1/sources` | `SourceRepository.library_page` (`backend/app/sources/repository.py`), keyset-paginated, newest first |
| `GET /api/v1/sources/{id}` | `_source_detail` (joins the Source, its original Artifact and its latest run) |
| `GET /api/v1/sources/{id}/media` | the original artifact's bytes, with an ETag |
| `DELETE /api/v1/sources/{id}` | `recycle_source` (`backend/app/sources/lifecycle.py`) |
| `POST /api/v1/sources/{id}/restore` | `restore_source` (same file) |
| `POST /api/v1/sources/{id}/permanent-delete` | `PermanentSourceDeletion` (`backend/app/sources/permanent_delete.py`) |

Tests: `tests/integration/test_api_sources.py`, `test_api_source_lifecycle.py`, `test_api_source_permanent_delete.py`,
`test_import_source.py`, `test_source_recycle.py`.

## 3. How it works: the routes

### `POST /api/v1/sources/import` (201)

Request: `{"path": "<absolute path on this machine>", "storage_mode": "MANAGED" | "REFERENCED", "display_name": "optional"}`.
The path must be absolute (validated; a relative one is `422`). The shell's native file picker supplies it. `MANAGED`
(the default) **copies** the bytes into the library; `REFERENCED` records a verified reference to your own file and
never touches it. The display name defaults to the file name without its extension. The file is decoded and checked
before anything is recorded.

Response: a `SourceDetail`:

```json
{"id": "bbc132a7-...", "type": "IMAGE", "display_name": "Red photo", "availability": "AVAILABLE",
 "processing_status": "NOT_PROCESSED", "thumbnail": null, "created_at": "...", "updated_at": "...",
 "state": "ACTIVE", "storage_mode": "MANAGED",
 "original": {"id": "bbc132a7-...", "kind": "ORIGINAL", "url": "/api/v1/sources/bbc132a7-.../media", "content_type": "image/png"},
 "width": 320, "height": 240, "mime_type": "image/png", "size_bytes": 14916,
 "original_filename": "photo1.png", "latest_processing_run": null, "recycled_at": null}
```

Never a filesystem path, only a media reference. Publishes the event `source.created`.

Errors (all observed unless marked): `400 SOURCE_FILE_UNREADABLE` (no such file, or a folder), `400
REFERENCED_FILE_INVALID`, `415 MEDIA_FORMAT_UNSUPPORTED` (a text file; only JPEG, PNG, BMP, WebP), `422 MEDIA_CORRUPT`
(a truncated PNG), `413 MEDIA_TOO_LARGE` (more than 100,000,000 pixels) and `413 SOURCE_FILE_TOO_LARGE` (more than
512 MiB): those two limits are *provisional*, `PROVISIONAL_MAX_PIXELS` and `PROVISIONAL_MAX_BYTES` in
`backend/api/startup.py`; `422 VALIDATION_ERROR` for a relative path or blank name; `503 IMPORT_UNAVAILABLE` if import
is not configured.

### `GET /api/v1/sources` (200)

Query: `state=ACTIVE|RECYCLED` (default `ACTIVE`), `limit`, `cursor`. Answer: a `Page` of `SourceSummary`
(`id, type, display_name, availability, processing_status, thumbnail, created_at, updated_at`). `availability` is the
state of the original's artifact (`AVAILABLE`, `MISSING`, ...); `processing_status` is `NOT_PROCESSED` or the latest
run's state. A permanently deleted source never appears.

### `GET /api/v1/sources/{id}` (200) and `.../media` (200 or 304)

The detail is above. `media` streams the Source's *own* original (never a path the client names) with `Content-Type`,
`Cache-Control: private, no-cache` and `ETag: "<the file's SHA-256>"`; a matching `If-None-Match` gets `304`.

### `DELETE /api/v1/sources/{id}` (204), `POST .../restore` (200), `POST .../permanent-delete` (204 or 202)

- **Recycle** is logical: the picture leaves the library view; its bytes, memory and history stay. A repeat is
  harmless. Refused with `409 SOURCE_BUSY` while a run is in flight. Event `source.updated`.
- **Restore** brings it back to `ACTIVE` without reprocessing; returns the `SourceDetail`.
- **Permanent delete** only from the bin: removes its bytes, faces, vectors and runs; Evidence and named people stay.
  `204` when nothing but a tombstone is left; `202 {"state":"DELETING","outstanding":[...]}` when part of it could not
  finish (a locked file), retried at the next start, and `/readiness` goes `DEGRADED` meanwhile. `409
  SOURCE_NOT_RECYCLED` if it is still `ACTIVE`. See [lifecycle](../../lifecycle/README.md).
- Any source being or already deleted is `404 SOURCE_NOT_FOUND` everywhere.

## 4. Try it

**Works with no models. Verified 2026-10-12** (backend running with the lesson-07 library; `$B`, `$H`, `$J`, `j` as in
[call the API](../01-call-the-api.md); `$P` is the folder with the pictures).

```bash
# import (managed)
curl -s -X POST -H "$H" -H "$J" -d "{\"path\":\"$P/red.png\",\"display_name\":\"Red photo\"}" $B/api/v1/sources/import
SID=$(curl -s -H "$H" "$B/api/v1/sources?limit=1" | j "d['items'][0]['id']")

# list: the active ones, then the bin
curl -s -H "$H" "$B/api/v1/sources?limit=50" | j "[i['display_name'] for i in d['items']]"
curl -s -H "$H" "$B/api/v1/sources?state=RECYCLED" | j "[i['display_name'] for i in d['items']]"

# recycle, see it in the bin, restore
curl -s -i -X DELETE -H "$H" $B/api/v1/sources/$SID | head -1                  # HTTP/1.1 204 No Content
curl -s -H "$H" "$B/api/v1/sources?state=RECYCLED" | j "[i['display_name'] for i in d['items']]"
curl -s -X POST -H "$H" $B/api/v1/sources/$SID/restore | j "d['state']"          # ACTIVE

# deleting for good while it is still active is refused
curl -s -X POST -H "$H" $B/api/v1/sources/$SID/permanent-delete
```

Observed: the last call answers `{"error":{"code":"SOURCE_NOT_RECYCLED","message":"Move the source to the recycle bin
before deleting it.","details":{"source_id":"..."},...}}`. Then `DELETE`, then `POST .../permanent-delete`: `HTTP/1.1 204
No Content`, and `GET /api/v1/sources/$SID` is `404 SOURCE_NOT_FOUND` (only a tombstone remains). **Do this only on a
picture you do not need.** The error calls from the verified run: a path that does not exist gave
`SOURCE_FILE_UNREADABLE`, a text file `MEDIA_FORMAT_UNSUPPORTED`, a truncated PNG `MEDIA_CORRUPT`, a folder
`SOURCE_FILE_UNREADABLE`, a relative path `VALIDATION_ERROR`.

## 5. Change it

The contract is pinned by `tests/integration/test_api_sources.py`. A one-line mutation, run on 2026-10-12: change
`NOT_PROCESSED = "NOT_PROCESSED"` at the top of `sources.py` to `"UNPROCESSED"` and run the file: it fails at
`test_a_managed_import_copies_the_image_into_the_library` (`processing_status` no longer equals `NOT_PROCESSED`).
Notice who else depends on that string: the front end has its own `NOT_PROCESSED` constant in
`frontend/src/features/status.ts`; a backend-only change would leave the screen showing the raw text, and nothing in
the generated types would warn you, because it is a plain `string`. That is a place where the contract is a
convention, not a type. Restore with `git restore backend/api/routes/sources.py`.

To add a field to `SourceSummary`, add it to the Pydantic class and to `_summary(...)`, run `test_api_sources.py`, then
`npm run generate:api` ([add a route](../02-add-a-route.md)).

## 6. Break it on purpose

Recycle a source while its processing run is still running: `409 SOURCE_BUSY` ("cancel that first"). Restore a source
that is already `ACTIVE`: it answers `200` (a repeat is harmless). Ask for the media of a recycled or missing original:
the reference in `original` is `null` unless the artifact is `AVAILABLE`, so a client can tell. Import the same file
twice: you get two Sources (verified in `test_importing_the_same_file_twice_makes_two_sources`).

## 7. Exercises

1. What is the difference between `MANAGED` and `REFERENCED`, and which one can the application never delete?
2. How does a client know a picture's original has gone missing?
3. What does `202` from `permanent-delete` mean, and what does `/readiness` show meanwhile?
4. Why does `media` take no path from the client?
5. Which status code do you get recycling a source mid-processing?

**Answers**

1. `MANAGED` copies the bytes into the library; `REFERENCED` points at your file. A referenced original is never
   modified or deleted by the application.
2. `availability` is `MISSING` in the summary and detail, and `original` is `null`.
3. Deletion was started but part of it (a locked file, say) is owed; it is retried at the next start; `recovery` is
   `DEGRADED` until then.
4. Serving a path the client names would let it read any file; the bytes come from the source's own artifact record.
5. `409 SOURCE_BUSY`.

## 8. Related files

- Next: [processing](processing.md) · [Routes index](README.md)
- [Sources and artifacts](../../domain/02-sources-and-artifacts.md), [recycle and restore](../../lifecycle/01-recycle-and-restore.md), [permanent delete](../../lifecycle/02-permanent-delete.md)
- [`backend/api/routes/sources.py`](../../../../../backend/api/routes/sources.py)
