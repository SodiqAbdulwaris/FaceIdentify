# M4 W3.3: the process command, processing-run reads and retry

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045 (endpoint schemas), TST-047 (state-changing commands)
- **Status:** partial; W3 continues with cancel, jobs, identities, occurrences, observations and system status
- **Commits:** PR (this change): `feat(api): add the process command, run reads and retry`

## What changed

- `backend/api/routes/processing.py` (new), behind the `Library` dependency:
  - `POST /sources/{id}/process` (202): checks the source exists (404 `SOURCE_NOT_FOUND`), builds
    the request from the host's development policy profile, commits a snapshot, a PENDING run and a
    QUEUED `INTERACTIVE` job atomically (`ProcessSourceUseCase`), wakes the scheduler after commit,
    and answers with the run and its job. A source that cannot be processed (not an ACTIVE image,
    original not `AVAILABLE`, request not resolvable) is 409 `SOURCE_NOT_PROCESSABLE` with the
    use case's reason; no processing profile is 503 `PROCESSING_UNAVAILABLE`.
  - `GET /processing-runs` (filters `source_id`, `state`), `GET /sources/{id}/processing-runs` and
    `GET /processing-runs/{id}`: keyset-paginated, newest first, cursor bound to the filters. Each run
    carries its source, parent run, timestamps, `failure_code` (never the failure detail text) and its
    latest source-processing job (state, priority, attempt, progress).
  - `POST /processing-runs/{id}/retry` (202): a new linked job and run through
    `RetryProcessingUseCase` (the old attempt is left exactly as it ended); 404 `RUN_NOT_FOUND`;
    409 `RUN_NOT_RETRYABLE` when the run is not failed/interrupted/not-resumable, has no
    processing job, or was already retried.
- `ProcessingSettings.request_for(session)` (new field) is how the host supplies the request a
  process command runs under; `ProcessingUnavailableError` means "none can be built yet" (for
  example, no model is registered). The client never chooses models or policy.
- `tests/fixtures/api.py`: `processing_api` fixture (registered fake catalog, planted perception,
  the real scheduler, executor, acceptance and index), the `serving` context shared with `api`, and
  the `imported` and `error` helpers the route tests share; `Api` carries the clock.

## Why

W3 of the completion plan: the second user-visible step of the desktop workflow (request
processing, watch it finish, retry a failure).

## Decisions

None new. Cancel, pause and resume are W3.4 (cancellation needs a use case that decides, per job
state, between cancelling a queued job and asking a running one to stop). Job reads are folded into
the run (the spec's `/jobs` resource follows with cancel). The request body is empty: priority is
`INTERACTIVE` for a user action; batch and re-processing priorities arrive with those commands.

## Verification

- `tests/integration/test_api_processing_routes.py` (13): a requested run is accepted, tracked and
  really completed (the source's `processing_status` follows); unknown source; a source whose
  original is gone; no profile; processing not configured; listing newest first with filters;
  paging with a cursor bound to the query and forged keys refused; unknown state, source and run;
  a run listed without a job; retry creates a new linked run once and refuses a second; completed
  and unknown runs; a run without a processing job. `backend/api/routes/processing.py` is at 100%
  line and branch.
- Mutation probes (15 on the routes: priority, unknown-source check, each status mapping, cursor
  context, ordering, both filters, progress, retry 404, retry job type, failure detail exposure):
  all killed after a progress test closed one survivor. Two survivors that chose among several jobs
  for one run were deleted instead: a run has exactly one processing job, so that ordering guarded
  nothing.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,479 passed**, 100% coverage.
