# M4 W3.2: source import, list, detail and original media routes

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045 (endpoint schemas), TST-046 (error contract as exercised)
- **Status:** partial; W3 continues with the process command, runs/jobs, identities and system status
- **Commits:** PR (this change): `feat(api): add source import, list, detail and media routes`

## What changed

- `backend/api/routes/` (new package): `api_router` mounts every router under `/api/v1`;
  `create_backend_app` includes it, importing it lazily to avoid a cycle with `startup`.
- `backend/api/routes/sources.py`, all routes behind the `Library` dependency (503 until the
  library is open) and plain `def` so blocking database and file work runs in a worker thread:
  - `POST /sources/import` (201): an absolute `path` on this machine, `storage_mode` `MANAGED`
    (copy into the library) or `REFERENCED` (verified reference, the user's file untouched), and an
    optional `display_name`. Import creates the source and does not process it. Failures map to
    one code each: 413 `SOURCE_FILE_TOO_LARGE` / `MEDIA_TOO_LARGE`, 400 `SOURCE_FILE_UNREADABLE` /
    `REFERENCED_FILE_INVALID`, 415 `MEDIA_FORMAT_UNSUPPORTED`, 422 `MEDIA_CORRUPT`, 422
    `VALIDATION_ERROR` for a blank name. 503 `IMPORT_UNAVAILABLE` when the backend has no
    `MediaLimits` (the host does not pass them yet).
  - `GET /sources?state=ACTIVE|RECYCLED`: newest first, keyset-paginated on `(created_at, id)` with
    a cursor bound to the state; each item carries its latest run's state as `processing_status`
    (`NOT_PROCESSED` when none).
  - `GET /sources/{id}`: detail with the original as a media reference (a URL, never a path),
    dimensions, size, latest run; 404 `SOURCE_NOT_FOUND`.
  - `GET /sources/{id}/media`: streams the source's own original in 64 KiB chunks with its content
    type, an `ETag` (the artifact's SHA-256) and `Cache-Control: private, no-cache`; a matching
    `If-None-Match` gets `304`. 404 `SOURCE_FILE_MISSING` when the artifact is not `AVAILABLE` or
    the file has vanished. The bytes come only from the source's artifact; the client never names
    a path.
- `MediaLimits(max_pixels, max_bytes)` on `Backend`, passed to `create_backend_app`.
- `tests/fixtures/api.py`: the `api` fixture (real temporary library, lifespan run, authenticated
  client), shared by the route tests that follow.

## Why

W3 of the completion plan: the first user-visible slice of the desktop workflow (put an image into
the library, see it, view it).

## Decisions

None new. Thumbnails are not generated yet, so `thumbnail` is always `null` (the field exists so
the contract does not change). `MediaLimits` values for the real host are provisional constants to
be set when the host wires `ProcessingSettings` (W6).

## Verification

- `tests/integration/test_api_sources.py` (18): import both modes, every error mapping, relative
  and missing paths, blank name, pagination over ties and across states, forged and cross-query
  cursors, detail with the latest of two runs, media bytes/type/ETag/304, lost file, a missing
  hash, library gating, unconfigured import. `backend/api/routes` is at 100% line and branch.
- Mutation probes (12: matching, caching header, availability checks, cursor context, each status
  mapping, absolute-path rule, original reference, latest-run ordering, `has_more`, storage mode,
  pixel limit): all killed after adding the two-run test that closed the one survivor.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,466 passed**, 100% coverage.
