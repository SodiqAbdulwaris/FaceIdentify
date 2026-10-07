# M4 W6 (host side): the shell can stop the host by closing its standard input

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W6 · TST-047 (backend half)
- **Status:** done; the Tauri shell that uses it is the next change
- **Commits:** PR (this change): `feat(api): stop the host when its standard input closes`

## What changed

- `backend.api.host --stdin-lifeline` (off by default): the host watches its standard input, and
  when it reaches end of file (the shell closed it, or the shell ended, which closes it) the host
  shuts down gracefully: the lifespan releases the library lock, exactly as when the parent process
  ends. A daemon thread blocks on the read, so nothing polls the pipe; the input never carries
  commands. The existing `--parent-pid` watch stays; either one stops the host.
- `serve(..., lifeline=...)` takes the check (true while alive); `stdin_lifeline(stream)` builds it
  from a stream, so tests do not touch the real standard input.

## Why

Windows has no gentle signal to send a child. The shell needs a way to ask for a *clean* stop
(unlike killing the process): it keeps the pipe open while it wants the host to run and closes it to
ask for shutdown. `--parent-pid` alone only helps after the shell has already gone.

## Decisions

None new. The 2026-10-06 handshake decision (token through the environment, one JSON line on
stdout) is unchanged.

## Verification

- `tests/integration/test_api_host.py` (+5, 17 in all): the flag parses and is off by default; the
  lifeline stays alive when data arrives and goes only at end of file (a real pipe); `serve` stops
  gracefully when the lifeline is cut and the library lock is then free; `main` builds the lifeline
  only when asked; and a real host process exits with code 0 (not a kill) when its standard input
  is closed. `host.py` is at 100% line and branch.
- Mutation probes (7: lifeline ignored, parent watch dropped, built always, built never, inverted,
  not set at end of file, flag default on): all killed. (The probes hang the suite on purpose when
  they succeed, so they run under a hard time limit.)
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,539 passed**, 100% coverage.
