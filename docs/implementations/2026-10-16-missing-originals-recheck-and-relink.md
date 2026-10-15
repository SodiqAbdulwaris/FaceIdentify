# A missing original comes back: on-access recheck, Recheck file and Locate original (issue #179)

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 backlog; issue #179; TST-025 (storage manager: relinking)
- **Status:** done; backend and desktop screen, tested
- **Commits:** PR (number recorded when merged): `feat(sources): recheck and relink a missing original`,
  `docs: record the missing-original recheck`

## What changed

- `backend/app/sources/recheck.py` (new): `recheck_original` verifies a `MISSING` original again
  through the existing verifiers (`reverify_managed_artifact`, `reverify_referenced_artifact`), which
  accept only the recorded size and SHA-256. An original in any other state is left alone. A file
  that is there but cannot be read raises `OriginalUnreadableError` and changes nothing. An original
  with no recorded fingerprint raises `OriginalUnverifiableError` and stays missing (the referenced
  verifier alone would accept any file by its mere presence; found by the review). A managed file
  that is back but different is recorded as `MANAGED_CONTENT_CHANGED`, and as `MANAGED_FILE_MISSING`
  again once it is gone. A concurrent recheck or relink is settled by reading the state again.
- `backend/api/routes/sources.py`:
  - **On access:** `GET /sources/{id}` verifies a missing original again before answering
    (`recheck_if_missing`, best effort: an unreadable or unverifiable file leaves the answer to the
    route's own read). The library listing verifies nothing (no library-wide scan).
  - `POST /sources/{id}/recheck` ("Recheck file"): `200` with the source; `409
    SOURCE_FILE_UNREADABLE` when the file is there but unreadable; `409 SOURCE_FILE_UNVERIFIABLE`
    when the original has no recorded fingerprint; `404` for an unknown source.
  - `POST /sources/{id}/relink` `{"path": ...}` ("Locate original", referenced originals only):
    `200` with the source; `409 SOURCE_RELINK_MISMATCH` (different media), `409
    SOURCE_NOT_REFERENCED` (a managed original), `409 SOURCE_STATE_CONFLICT` (not missing), `409
    SOURCE_RELINK_UNVERIFIABLE` (no recorded fingerprint), `400 REFERENCED_FILE_INVALID` (inside the
    library's own storage, not a file, unreadable), `422` for a relative path.
  - `SourceDetail.availability_reason`: the original's failure code when it is not available
    (`MANAGED_FILE_MISSING`, `MANAGED_CONTENT_CHANGED`, `REFERENCED_FILE_MISSING`,
    `REFERENCED_CONTENT_CHANGED`), else `null`.
  - A recovered or relinked original is announced as `source.updated`. Answers never contain a path.
- `backend/api/routes/processing.py`: `POST /sources/{id}/process` and
  `POST /processing-runs/{id}/retry` call `recheck_if_missing` first.
- Desktop (`frontend/src/features/source/`): `MissingOriginal.tsx` shows **Recheck file** and, for a
  referenced original in the desktop app, **Locate original…** (the shell's existing native picture
  dialog); the outcome goes to the page notice ("The file is back." or "Still missing." with the
  reason); `missing.ts` words the reason (a changed file, referenced or managed, is said to have
  changed; otherwise the user is asked to put the file back). `openapi.json` and `schema.d.ts`
  regenerated; `endpoints.ts` gains `recheckSource`, `relinkSource`.
- Tests: `tests/integration/test_api_source_recheck.py` (19: the routes, the use case's own race and
  unknown-source edges, and the review's three cases: no fingerprint, a managed file back but
  different, retry without opening the source); two existing tests that marked a present file
  `MISSING` by hand now really remove it, since opening or processing such a source rightly finds the
  file and brings it back (`test_api_sources.py`, `test_api_processing_routes.py`);
  `MissingOriginal.test.tsx` (7) and `missing.test.ts` (2).

## Why

Issue #179: the reverify and relink services were built and tested but nothing called them, so a
restored file never came back and nothing could relink. The owner's decision of 2026-10-14 (locked,
on the issue) chose on-access verification plus manual recovery, no startup scan and no periodic
recheck, with the contract this change follows point by point (integrity before availability, Recheck
and Locate, no filename-as-proof, failure leaves the item missing with an actionable status, no
blocking of unrelated browsing, idempotent, trust boundary kept, restart persistence tested).

## Decisions

- **"Opened" means the source detail read** (`GET /sources/{id}`), the request the source screen
  makes first; the media route is not used by the screen while the original is missing, and the
  listing deliberately verifies nothing. "Used" means processing and retrying a run (the review
  showed a retry must not rely on the screen having opened the source first).
- **A recheck only acts on `MISSING`.** An `AVAILABLE` original is not re-hashed on request; the
  existing media route already reports a file lost behind the application's back.
- **Managed originals are rechecked where the library keeps them, never relinked** (the decision's
  point 2).
- **No spec text changed:** the routes implement the owner's locked contract on #179 and API section
  59 (relinking verifies the candidate; different media is replacement). The new routes and the
  `availability_reason` field are in the generated OpenAPI document.
- **The unreadable case is tested by making the hash raise `PermissionError`** (a locked file cannot be
  produced portably in a test); every other test uses real files.

## Verification

- `uv run pytest -q tests/integration/test_api_source_recheck.py tests/integration/test_api_sources.py
  tests/integration/test_api_processing_routes.py`: 50 passed. Without the change (routes restored,
  `recheck.py` removed) 13 of the 14 route tests fail; the one that passes is "a listing does not verify
  anything", true before and after.
- Full backend gate (ruff format, ruff check, mypy Windows and Linux, `pytest --cov`): see the PR.
- Frontend: `npm test` 200 passed, `npm run typecheck`, `npm run lint -- --deny-warnings`,
  `npm run build`: clean.
- Not verified in the real desktop window (the native dialog path is covered by a mocked shell).

## Open issues / follow-ups

- Video originals (M6) will make hashing on open expensive for a large referenced file whose size is
  unchanged; the size check comes first, so a changed file is usually refused without hashing.
