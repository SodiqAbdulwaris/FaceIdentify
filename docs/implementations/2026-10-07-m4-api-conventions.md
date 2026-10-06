# M4 W3.1: the API conventions every route inherits

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045 (first part)
- **Status:** partial (W3 continues: import, queries and media, process, runs and jobs, identities)
- **Commits:** PR (this change): `feat(api): add the error contract, cursors and library gating`

## What changed

- `backend/api/errors.py`: `ApiError` and the handlers that give every REST error one shape,
  `{"error": {code, message, details, retryable, diagnostic_id}}` (API section 23). Expected errors
  keep their status and code; validation failures become `422 VALIDATION_ERROR` naming the field and
  Pydantic's stable error type but never what the client sent or Pydantic's per-field message (a
  custom validator may build it from the value); unknown routes and methods are `NOT_FOUND` and
  `METHOD_NOT_ALLOWED`; anything unexpected is `500 INTERNAL_ERROR` with a diagnostic id and no
  message or traceback (the id is logged with the exception class). The authentication failure uses
  the same full shape (it had two fields).
- `backend/api/pagination.py`: forward-only keyset pagination (sections 26 and 27): `Page`,
  `PageParams` (default limit 50, maximum 200, a cursor of at most 512 characters, its key scalars only),
  `encode_cursor` / `decode_cursor` (versioned, URL-safe, bound to a *context* string so a cursor
  from one query is `400 INVALID_CURSOR` on another) and `paginate` (fetch `limit + 1`; the probe
  row is `has_more`).
- `backend/api/dependencies.py`: `Library`, a dependency that answers `503 LIBRARY_UNAVAILABLE`
  until the backend reports the library open (`READY` or `DEGRADED`): retryable while starting, not
  after a failed start or at shutdown; the body is the state and, for a failed start, the exception
  class name.

## Why

Every W3 route needs the same error shape, cursors and gating; building them once, with their own
tests, keeps the routes thin (the architecture rule) and the contract uniform.

## Decisions

New machine codes beyond the spec's representative list: `NOT_FOUND`, `METHOD_NOT_ALLOWED`,
`HTTP_ERROR`, `UNAUTHORIZED` (already used) and `LIBRARY_UNAVAILABLE`. The spec says its list is
representative. A limit above 200 is refused (`422`), not clamped.

## Verification

- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,446 passed in 270.06s, 100% line and branch coverage**.
- `tests/contracts/test_api_conventions.py` (24) with a throwaway router: each error kind and the
  shape of every field, no echo of client input, the log carrying the diagnostic id, the 503 states,
  cursor round trip and every malformed kind, a walk through a collection page by page, a page that
  ends exactly on the limit, bad limits and cursors. Nine guard mutations (echoing input, leaking
  the message, ignoring the cursor context or version, an off-by-one `has_more`, a lifted maximum,
  serving while initializing, retryability, dropping the failure name) were each caught.

## Open issues / follow-ups

W3.2 onward: the real routes, each thin over a use case, using these pieces. The OpenAPI schema
that W5 generates will describe `ApiError` bodies once the routes declare them.
