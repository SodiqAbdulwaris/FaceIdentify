# The API: conventions and the route map

Everything the front end does, and everything you can do by hand with `curl`, goes through the backend's HTTP
API under `/api/v1`, plus a WebSocket for events. This page is the one-page summary of the **rules every route
shares**, and the map of all 39 operations (verified from the generated OpenAPI document on 2026-10-12).

## The lessons in this folder

| Lesson | What it gives you |
|---|---|
| [01 Call the API](01-call-the-api.md) | a tour with `curl` and Python, every kind of call |
| [02 Add a route](02-add-a-route.md) | the exact steps, with what fails when you skip one |
| [03 OpenAPI and the contract](03-openapi-and-contract.md) | how `openapi.json` and the TypeScript types stay in step |
| [routes/](routes/README.md) | one lesson per route module: sources, processing, jobs, memory, people, corrections, identity changes, search, face search |

## The rules every route shares

1. **Authentication.** Every HTTP request, `/health` and `/readiness` included, must carry
   `Authorization: Bearer <the launch token>`, or it gets `401 UNAUTHORIZED` with a `WWW-Authenticate: Bearer`
   header. The token is checked in constant time (`hmac.compare_digest`). It is a per-launch capability, not a login.
2. **Loopback only.** The server binds `127.0.0.1` on a random port.
3. **Library gating.** A route that uses the library takes `Library` (`backend/api/dependencies.py`). Until the
   backend is `READY` or `DEGRADED` it answers `503 LIBRARY_UNAVAILABLE` (retryable only while still starting).
4. **One error shape**, for every failure:

   ```json
   {"error": {"code": "SOURCE_NOT_FOUND", "message": "The requested source could not be found.",
              "details": {"source_id": "..."}, "retryable": false, "diagnostic_id": null}}
   ```

   `code` is stable and machine-readable; `message` is for people; `details` carries ids and reasons, never what you
   sent; `retryable` says whether trying again may work; `diagnostic_id` appears only on `500 INTERNAL_ERROR`.
   Validation failures are `422 VALIDATION_ERROR` naming the field location and the rule type (`uuid_parsing`,
   `value_error`) and never echoing the input. Unknown path `NOT_FOUND`, wrong method `METHOD_NOT_ALLOWED`.
5. **Cursor pagination** on collections: `?limit=` (1 to 200, default 50) and `?cursor=`; the answer is
   `{"items": [...], "page": {"next_cursor": "...", "has_more": true}}`. A cursor is opaque, versioned and tied to
   the query that made it: another query's cursor is `400 INVALID_CURSOR`. Orders always end in a unique tie-breaker.
6. **Status codes with meaning.** `201` created; `202` accepted (the work happens later: process, cancel, retry);
   `204` done with nothing to say; `400`/`413`/`415`/`422` the input is wrong; `404` not found (also for things being
   or already permanently deleted); `409` the state does not allow it, or your view is stale; `429` busy; `503` not
   available.
7. **Thin routes.** A route validates the request, calls a use case or repository, and shapes the answer as an API
   schema, never a database row and never a file path. Routes are plain `def` so FastAPI runs them in a thread.
8. **Writes announce after the commit**: `backend.announce(...)` publishes an event to the WebSocket, best effort
   ([events](../architecture/07-events.md)). REST stays the truth.
9. **Optimistic concurrency.** Writers carry the revision they saw (`expected_revision`, `expected_identity_id`,
   `revision` in merge); a stale one is a `409` (`PERSON_REVISION_CONFLICT`, `IDENTITY_CHANGED`, `OCCURRENCE_MOVED`).

## The route map (39 operations)

| Module | Operations |
|---|---|
| [`sources.py`](routes/sources.md) | `POST /sources/import` · `GET /sources` · `GET /sources/{id}` · `GET /sources/{id}/media` · `DELETE /sources/{id}` (recycle) · `POST /sources/{id}/restore` · `POST /sources/{id}/permanent-delete` |
| [`processing.py`](routes/processing.md) | `POST /sources/{id}/process` · `GET /processing-runs` · `GET /sources/{id}/processing-runs` · `GET /processing-runs/{id}` · `POST /processing-runs/{id}/cancel` · `POST /processing-runs/{id}/retry` |
| [`jobs.py`](routes/jobs.md) | `GET /jobs` · `GET /jobs/{id}` · `POST /jobs/{id}/cancel` |
| [`memory.py`](routes/memory.md) | `GET /identities` · `GET /identities/{id}` · `GET /sources/{id}/occurrences` · `GET /identities/{id}/occurrences` |
| [`people.py`](routes/people.md) | `POST /people` (name an identity) · `GET /people` · `GET /people/{id}` · `PATCH /people/{id}` · `POST /people/{id}/assign-identity` · `POST /people/{id}/remove-identity` · `POST /people/{id}/forget` |
| [`corrections.py`](routes/corrections.md) | `GET /occurrences/{id}` · `POST /occurrences/{id}/confirm` · `POST /occurrences/{id}/reassign` · `GET /sources/{id}/unresolved-faces` · `POST /representations/{id}/resolve` |
| [`identity_changes.py`](routes/identity-changes.md) | `POST /identities/merge` · `POST /identities/{id}/split` · `POST /identities/{id}/forget` |
| [`search.py`](routes/search.md) | `GET /search` |
| [`face_search.py`](routes/face-search.md) | `POST /search/face` |
| `app.py` | `GET /health` · `GET /readiness` · `WS /api/v1/events` |

There is **no status route**: `/readiness` and `/health` are the status read model (owner decision 2026-10-07).

## Where the shared parts live

| Part | File |
|---|---|
| The app factory, auth middleware, `/health`, `/readiness`, the WebSocket | `backend/api/app.py` |
| The lifecycle (`Backend`), library opening, scheduler start, `announce` | `backend/api/startup.py` |
| `Library`, `get_backend` | `backend/api/dependencies.py` |
| The error shape and handlers | `backend/api/errors.py` |
| Pagination | `backend/api/pagination.py` |
| The event hub | `backend/api/events.py` |
| Router registration | `backend/api/routes/__init__.py` |
| The OpenAPI document | `backend/api/openapi.py` → `frontend/src/api/openapi.json` |

The authoritative contract is `docs/specs/API and Contracts.md`; if this page and the spec disagree, the spec wins.

Back to [03 The backend](../README.md).
