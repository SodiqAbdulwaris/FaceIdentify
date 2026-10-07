# M4 W3.6: every run reports the policy it was frozen under

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045; plan decision 1 (development policy profile)
- **Status:** done for W3 (the REST surface the M4 workflow needs); WebSocket events are W4
- **Commits:** PR (this change): `feat(api): report each run's policy provenance`

## What changed

- `ProcessingRunDetail` (every run read and every command response) gains `policy`:
  `calibration_mode`, `decision_policy_version` and `calibrated` (false exactly while the frozen
  mode is `UNCALIBRATED`). It is read from the run's immutable configuration snapshot, so it is
  what was true when the run was requested, not what is configured now.
- This is how a screen shows the owner's decision that results from the development policy profile
  are labelled uncalibrated and non-release: the label comes from provenance, not from a client
  constant, and disappears only when a run is frozen under a calibrated profile (TST-044).

## Why

The 2026-10-06 plan decision requires the uncalibrated status to be "surfaced as such in the UI".
Putting it on the run keeps one source of truth and makes the notice survive restarts.

## Decisions

> **Decision 2026-10-07 (agent's, for the owner to confirm; M4 W3): there is no separate system
> status route.** The plan listed "system status" among the W3 reads. `/health` and `/readiness`
> already report the lifecycle and every capability (`scheduler` is `NOT_CONFIGURED`, `READY`,
> `DEGRADED` or `STOPPED`), which is all a screen needs to enable or disable "Process". The spec's
> `GET /runtime/status` describes runtime packages and belongs with the runtime work (M8). Adding a
> third status endpoint would only duplicate `/readiness`.

> **Decision 2026-10-07:** Owner confirmed. `/health` answers whether the sidecar process and API
> are alive; `/readiness` answers whether this instance can serve the application and returns
> structured component state (database, scheduler, ML runtime and catalog, index), including
> `DEGRADED`. The frontend treats `/readiness` as the authoritative operational-status read model.

## Verification

- `tests/integration/test_api_processing_routes.py` (16): a requested run reports
  `UNCALIBRATED`, `m3-fixture-v1` and `calibrated: false`; a run built on a snapshot frozen
  `CALIBRATED` with no policy version reports `calibrated: true` and no version. `processing.py`
  is at 100% line and branch.
- Mutation probes (4: always uncalibrated, always calibrated, version dropped, mode ignored): all
  killed.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,502 passed**, 100% coverage.
