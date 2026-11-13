# Backend coverage is 100% again, and CI now fails below it

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** CI-002, CI-003 (backend tests and coverage); found in the final full-gate run
- **Status:** done
- **Commits:** PR (number recorded when merged): `test: cover the last five lines and enforce full coverage`

## What changed

- `.github/workflows/ci.yml`: the backend test command ends with `--cov-fail-under=100`.
- Four tests for the five lines (two branches) that were not covered on `main`:
  - `tests/integration/test_ml_perception_handlers.py`: an object the module did not load has no
    adapter (`onnx_session.adapter_of`, the `TypeError` path).
  - `tests/integration/test_runtime_package_store.py`: an installed package whose manifest is
    missing or not JSON is never treated as an upgrade (`RuntimePackageStore._only_adds_variants`).
  - `tests/integration/test_api_cameras.py`: a search waiting for a session's first picture, when
    that session ends without one, opens the camera itself (`CameraService.capture`). The test
    stops the session only once the search is inside its wait (an event that records the wait, no
    sleep), so it always takes the branch it is for.
  - `tests/integration/test_camera_session.py`: an encounter whose face changed while it was being
    accepted is refused and leaves no occurrence (`accept_encounter`).

## Why

Backend coverage has been 100% at every milestone gate (the M5 declaration of 2026-10-21 records
3,237 tests at 100%), and every agent brief of this run said to keep it there, but no rule file
states the number and nothing enforced it: the CI command reported coverage and never failed on
it. `.agents/rules/testing.md` allows a numeric threshold only with a measured baseline; 100% is
that baseline. The full gate run on `main`
at `c0b7e36` (and CI's own log for that commit) showed 99%: 13,813 statements, 5 missed, 2 partial
branches, in `cameras/service.py`, `processing/accept_run.py`, `runtime/package_store.py` and
`ml/worker/onnx_session.py`, all from work merged on 2026-11-13.

## Decisions

The threshold is in the CI command, not in `pyproject.toml`: a threshold in the configuration would
also fail every targeted local run (`pytest tests/x --cov`), which agents use between full gates.

## Verification

On this branch: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and
`uv run mypy --platform linux` clean. The four test files, 181 tests, passed, with
`cameras/service.py` and `onnx_session.py` at 100% from those files alone. The full suite's 100% is
proven by CI on this PR's head, which now fails otherwise (full local gate on `main` before the
change: 3,735 passed, 99%).

## Open issues / follow-ups

None.
