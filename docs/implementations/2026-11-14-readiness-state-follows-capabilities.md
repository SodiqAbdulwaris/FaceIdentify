# Readiness reports the state that is true now

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M8 (first run); found driving the real backend by hand in the final check
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(api): report the readiness state that is true now`

## What changed

- `backend/api/startup.py`, `Backend.readiness()`: while the library is open (`READY` or
  `DEGRADED`), the reported `state` is derived from the capabilities being reported, by the rule
  already applied when the library opens (any capability `DEGRADED` or `UNAVAILABLE` means
  `DEGRADED`). The lifecycle state the backend keeps for itself (which decides whether requests are
  served) is unchanged.
- `tests/integration/test_api_runtime_models.py`: a first run without models reports `DEGRADED`,
  the same backend reports `READY` once the models are there, and `DEGRADED` again when work is owed
  later.

## Why

The state was computed once, when the library opened. On a first run the models are not installed
yet, so the backend opened `DEGRADED`; after the user installed the models and chose a recognition
mode, `/readiness` listed every capability `READY` and still said `"state": "DEGRADED"` until the
next start. The reverse also held: a capability marked `DEGRADED` during the run (a deletion to
finish at the next start) left the state `READY`.

Seen on 2026-11-14 with the real host on a scratch library and the real models: after the first-run
install and the mode choice, and after pictures and a video were processed on
`DmlExecutionProvider`, the answer was `DEGRADED` with twelve capabilities, none of them degraded.

The web app treats `READY` and `DEGRADED` alike (`BackendGate.tsx`), so no screen was wrong; the
contract was.

## Decisions

Delegated (owner, 2026-11-09; reversible): the reported state follows the reported capabilities.
No spec text changes: API and Contracts already says the application "may be usable in a degraded
state" when a capability is unavailable, which is what the report now says at every moment.

## Verification

`uv run ruff format --check`, `uv run ruff check .`, `uv run mypy`: clean. The eleven test files
that read `/readiness` or the word `DEGRADED`, plus `tests/contracts`: 367 passed. Full gate and
coverage (enforced at 100%): CI on the PR's head.

## Open issues / follow-ups

None.
