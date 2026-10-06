# M4 W1.1: the API lifespan and lifecycle-backed readiness

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M4 W1 · TST-048 (backend half)
- **Status:** partial (W1 continues with the sidecar host, W1.2)
- **Commits:** PR (this change): `feat(api): open the library in the lifespan and report readiness`

## What changed

- `backend/api/startup.py` (new): `Backend` (the library once opened and the lifecycle around it),
  `LibrarySettings`, `capabilities_from` (readiness capabilities from the recovery report),
  `backend_lifespan` and `create_backend_app`.
- FastAPI starts serving at once; `open_library` (lock, migrations, recovery, indexes) then runs in a
  worker thread, so `/readiness` answers `INITIALIZING` while it works, then `READY`, `DEGRADED`
  (a reconstructible capability has outstanding work) or `FAILED` (the library could not open; the
  failure is the exception's class name only, never a path or the capability) and the process keeps
  answering. Leaving the application waits for an open in flight, closes the library and releases
  the lock.
- `/readiness` now also returns `capabilities` (database, storage, index, recovery, ml_worker,
  scheduler) once known; the ML worker and the scheduler are `NOT_STARTED` until W2 builds them.
  `create_app` takes an optional lifespan; the old two-field body is unchanged when no capabilities
  are given.

## Why

Architecture section 22 (staged startup, capability-based readiness, `DEGRADED` for recoverable
subsystems) and the plan constraint that recovery completes before the scheduler claims work: the
scheduler (W2) will be created only after the library is reported open.

## Decisions

Lifecycle states used: `INITIALIZING`, `READY`, `DEGRADED`, `FAILED`, `SHUTTING_DOWN` (the spec
lists `BOOTING`, `INITIALIZING`, `RECOVERING`, `READY`, `DEGRADED`, `FAILED` as examples; `open_library`
is one blocking call, so `RECOVERING` cannot be reported separately yet). Until W2 the ML worker and
scheduler are reported `NOT_STARTED` and do not degrade the state; W2 will make them required.

## Verification

- Full gate (2026-10-06): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,373 passed in 238.87s, 100% line and branch coverage**.
- `tests/integration/test_api_lifespan.py` (14) on a real temporary library, through the lifespan and
  `httpx.ASGITransport`, never sleeping on a clock: ready, still opening, failed to open, held by
  another backend, a degraded capability, shutdown during an open, per-capability degradation.
  100% line and branch coverage of `backend/api`. Six guard mutations, each caught after two
  gaps were closed with tests (a degraded capability reaching the overall state, and shutdown during
  an open).
- Starlette's `TestClient` is deprecated with `httpx` here (warnings are errors), so the tests drive
  `app.router.lifespan_context` directly.

## Open issues / follow-ups

W3 routes that use the library must answer 503 until the state is `READY` or `DEGRADED` (none exist yet).

W1.2: the sidecar host (a server, which needs `uvicorn`, a new dependency recorded then), the
stdout handshake, the environment token and the parent-process watch. W2: the scheduler, which
starts only after this reports the library open.
