# M4 W1.2: the sidecar host

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W1 · TST-047 (backend half), TST-048
- **Status:** done for W1 (the Tauri side that spawns it is W6)
- **Commits:** PR (this change): `feat(api): add the loopback sidecar host`

## What changed

- `backend/api/host.py` (new): `python -m backend.api.host --library-root R --local-state-root L
  [--parent-pid P]`. It binds `127.0.0.1` on a port the OS picks (no `SO_REUSEADDR`: on Windows that
  would let another process share the port), serves the authenticated application
  (`create_backend_app`, W1.1), and writes exactly one JSON line to stdout once the server accepts
  connections: `{"schema_version":1,"protocol":"faceidentify.v1","host":...,"port":...,"pid":...}`
  where `host` is the address the socket is actually bound to. Nothing else goes to stdout.
- The per-launch capability comes only from `FACEIDENTIFY_LAUNCH_TOKEN`, validated before anything
  is bound; there is no command-line option for it, and it is never printed or logged. A missing or
  malformed one exits 2 without echoing it.
- `--parent-pid`: the shell's process id; the host polls it (Windows `OpenProcess` plus
  `WaitForSingleObject`, never `os.kill(pid, 0)`, which would terminate the process on Windows) and
  shuts down gracefully when it ends, so the lifespan releases the library lock.
- `pyproject.toml` / `uv.lock`: **new dependencies `uvicorn` and `websockets`** (see Decisions).

## Why

The M4 decisions of 2026-10-06 (stdout JSON handshake, token through an inherited environment
variable) and tech-stack section 5 (a Tauri-managed sidecar on loopback with a dynamic port).

## Decisions

> **Decision 2026-10-07 (agent, delegated; flag if you disagree):** the ASGI server is `uvicorn`
> (FastAPI's standard server) with `websockets` for the events endpoint. FastAPI is locked, but no
> document names a server; neither was installed. Not `uvicorn[standard]`: uvloop does not support
> Windows and httptools is optional. The owner was asleep and had asked for the agent's best judgement.

The retry policies and index catch-up limits the host passes to `open_library` are constants named
`PROVISIONAL_*`: unmeasured operational limits, not product defaults, to be set from benchmarks.

## Verification

- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,385 passed in 412.80s, 100% line and branch coverage**.
- `tests/integration/test_api_host.py` (11): the pure pieces; the host served in this process on a
  real loopback socket (handshake, authentication, `READY`, a graceful stop when the parent ends,
  library lock released); a server that cannot start raises and closes its socket; `main` with a gone
  parent, bad and missing capability, and the real argv and environment; the module run as a script;
  and one real child process (handshake read, `/health` with the capability, killed, library free).
  100% line and branch coverage of `backend/api`.
- The tests found a real defect: when the server failed to start, the cleanup re-awaited the failed
  task before closing the listening socket, leaking it. Fixed.
- Mutations (restored byte-identically): binding every interface, never watching the parent, a second
  handshake line, accepting the token on the command line, and skipping token validation each fail a test.

## Open issues / follow-ups

W6 (Tauri) spawns this, reads the handshake and passes the token and its own pid. A shutdown request
over the API and `SHUTTING_DOWN` signalling are not built; graceful stop today is the parent-process
watch (and the platform's termination signal).
