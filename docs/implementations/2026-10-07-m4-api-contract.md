# M4 W5: the generated API contract

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W5 · TST-046 (generated contract and its sync)
- **Status:** done; the frontend consumes the generated types in W7
- **Commits:** PR (this change): `feat(api): generate the OpenAPI document and TypeScript types`

## What changed

- `backend/api/openapi.py` (new): `openapi_document()` builds the document from the real
  application (`create_backend_app`, with placeholder settings: building opens nothing), `render()`
  makes stable text (sorted keys, two-space indent, LF), and `python -m backend.api.openapi` writes
  `frontend/src/api/openapi.json`.
- `npm run generate:api` (root) does that, then runs `openapi-typescript` (a frontend dev
  dependency, plan decision 5) to write `frontend/src/api/schema.d.ts`. Both files are committed.
- Every `/api/v1` operation now declares the one error shape: an `ErrorEnvelope` / `ErrorBody` model
  (`backend/api/errors.py`) is the `default` response of the versioned router, so a generated client
  types failures as it types successes. Operation ids are the route function names
  (`import_source`, `list_runs`, `cancel_job`), not FastAPI's long path-derived ones, so the
  generated client reads well.
- **Sync, in both directions.** `tests/contracts/test_openapi_contract.py` fails the backend suite
  when the committed document is stale ("run `npm run generate:api`"); the frontend CI job
  regenerates the TypeScript types from the committed document and fails if `git status` shows any change under
  `frontend/src/api`, then type-checks them.
- `.npmrc` sets `legacy-peer-deps=true`: openapi-typescript 7.13 declares a peer range of
  TypeScript `^5.x` while the app is on TypeScript 6 (an npm `overrides` entry does not apply to
  peer ranges). The generator works with TypeScript 6 (its output type-checks), and the lockfile is
  honoured by `npm ci` without flags; the file records why and when to drop it.

> **Decision 2026-10-07 (owner):** accepted as a temporary exception. The setting is repository-wide
> and makes npm ignore every peer conflict, not only this one, so it must stay explained: dependency
> openapi-typescript 7.13, reason TypeScript 6 outside its `^5` peer range, removal condition
> openapi-typescript officially supports the project's TypeScript major. `.npmrc` states all three.

## Why

W5 of the completion plan: one source of truth for request and response shapes, so the frontend
(W7) cannot drift from the backend and a contract change is a reviewed diff.

## Decisions

None new. The WebSocket envelope is not in OpenAPI (it is not an HTTP operation); W7 types it by
hand from the documented envelope.

## Verification

- `tests/contracts/test_openapi_contract.py` (6): the committed document equals a fresh one; every
  API operation declares `ErrorEnvelope` and the body's five fields; operation ids are unique
  function names; no secret or placeholder path in the document; the exporter writes the rendered
  text with LF endings; running the module as a script writes the committed path. `openapi.py` is
  at 100% line and branch.
- Mutation probes (6: unsorted keys, CRLF output, no default error, default operation ids, a
  missing error field, plus the stale-document check itself): all killed.
- Frontend (2026-10-07): `npm run generate:api` regenerates both files unchanged; `npm run
  typecheck`, `npm run lint` and `npm test` pass with the generated types present.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,527 passed**, 100% coverage.
