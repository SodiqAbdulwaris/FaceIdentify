# Routes: processing (`backend/api/routes/processing.py`)

## 1. What this is and why it exists

Importing put a picture in the library; **processing** is what finds its faces and decides who they are. It is a
long job, so the API does not do it inside the request. `POST /sources/{id}/process` only *writes down* the request
(a **Job** that schedules the work and a **ProcessingRun** that records it, with a frozen copy of all the settings)
and answers `202 Accepted`. A background loop does the work. This module is how you start that, watch it, stop it
and try it again. See [processing](../../processing/README.md) for what happens inside.

## 2. Where it lives

| Route | Use case |
|---|---|
| `POST /api/v1/sources/{id}/process` (202) | `ProcessSourceUseCase.process` (`backend/app/processing/process_source.py`), built from `ProcessingSettings.request_for` |
| `GET /api/v1/processing-runs` (200) | a paged query over `ProcessingRun` (filters `source_id`, `state`) |
| `GET /api/v1/sources/{id}/processing-runs` (200) | the same for one source (404 if the source is gone) |
| `GET /api/v1/processing-runs/{id}` (200) | one run with its job |
| `POST /api/v1/processing-runs/{id}/cancel` (202) | `CancelProcessingUseCase` (`backend/app/processing/cancel.py`) |
| `POST /api/v1/processing-runs/{id}/retry` (202) | `RetryProcessingUseCase` (`backend/app/processing/retry.py`) |

Tests: `tests/integration/test_api_processing_routes.py` (and `test_api_processing.py`, `test_api_jobs.py`, 33 tests
together), `test_cancel_processing.py`, `test_process_source.py`.

## 3. How it works: the routes

### `POST /api/v1/sources/{id}/process`

No body. It checks the source exists (`404 SOURCE_NOT_FOUND`), asks the profile for the **processing request**
(`503 PROCESSING_UNAVAILABLE` if there is no usable configuration, for example the real profile with no model package or no
policy file), and in **one transaction** creates the Job (priority `INTERACTIVE`) and the run with its frozen snapshot. Then
it wakes the scheduler. Answer, a `ProcessingRunDetail`:

```json
{"id": "b0df0d0d-...", "source_id": "bbc132a7-...", "state": "PENDING", "parent_run_id": null,
 "requested_at": "...", "started_at": null, "completed_at": null, "failed_at": null, "failure_code": null,
 "policy": {"calibration_mode": "UNCALIBRATED", "decision_policy_version": "development-uncalibrated-v1",
            "calibrated": false, "automatic_matching": true},
 "job": {"id": "6c805fbf-...", "state": "QUEUED", "priority": "INTERACTIVE", "attempt_number": 1, "progress": null}}
```

`policy` tells a screen whether results come from an uncalibrated policy and whether automatic matching can happen at
all (`automatic_matching: false` when the frozen threshold is above 1). A source whose original is missing is `409
SOURCE_NOT_PROCESSABLE` with `details.reason` (observed: "source ...'s original is not available"). Event:
`processing_run.created`.

### The run's life

States: `PENDING` (queued) → `RUNNING` → `COMPLETED`, or `FAILED`, `CANCELLED`, `INTERRUPTED` (found running at a
restart), `NOT_RESUMABLE`; with `PAUSING`, `PAUSED`, `CANCELLING`, `FINALIZING` in between. Each change publishes
`processing_run.updated` with `{state, source_id}`. In the verified run the events were `created PENDING`, `updated
RUNNING`, `updated COMPLETED`.

### Cancel and retry

- **Cancel**: a *queued* run is cancelled at once; a *running* one becomes `CANCELLING` and the executor settles it
  at the next safe boundary (it never stops mid-step). A repeat is harmless. A finished run: `409 RUN_NOT_CANCELLABLE`
  with the reason ("run ... is COMPLETED, which cannot be cancelled", observed).
- **Retry**: only a `FAILED`, `INTERRUPTED` or `NOT_RESUMABLE` run; it makes a **new** Job and a **new** run
  (`parent_run_id` set, a copy of the frozen snapshot). Anything else: `409 RUN_NOT_RETRYABLE` ("job ... is COMPLETED,
  which cannot be retried", observed).
- Listings take `limit`, `cursor`, and for `/processing-runs` also `source_id` and `state` (an unknown state is `422`).

## 4. Try it

**Works with no models. Verified 2026-10-12** (variables as in [call the API](../01-call-the-api.md)).

```bash
SID=$(curl -s -H "$H" "$B/api/v1/sources?limit=1" | j "d['items'][0]['id']")
curl -s -X POST -H "$H" $B/api/v1/sources/$SID/process                      # 202, state PENDING, job QUEUED
RUN=$(curl -s -H "$H" "$B/api/v1/sources/$SID/processing-runs?limit=1" | j "d['items'][0]['id']")
sleep 1; curl -s -H "$H" $B/api/v1/processing-runs/$RUN | j "(d['state'], d['job']['state'])"     # ('COMPLETED', 'COMPLETED')
curl -s -H "$H" "$B/api/v1/processing-runs?state=COMPLETED&limit=3" | j "[r['state'] for r in d['items']]"
curl -s -X POST -H "$H" $B/api/v1/processing-runs/$RUN/cancel               # 409 RUN_NOT_CANCELLABLE
curl -s -X POST -H "$H" $B/api/v1/processing-runs/$RUN/retry                # 409 RUN_NOT_RETRYABLE
```

Expected: exactly those states and the two `409` bodies quoted above. To *see* a cancel work you need a run that
has not started; by hand it is too fast. The test does it by switching the scheduler wake off:
`uv run pytest tests/integration/test_api_jobs.py -q` (`test_a_queued_run_is_cancelled_through_the_run_and_a_repeat_is_harmless`).
The retry-as-a-new-linked-run behaviour is `test_a_failed_run_is_retried_once_as_a_new_linked_run` in
`test_api_processing_routes.py`. Processing the same source again (another `POST .../process`) is allowed and
creates a second run and more occurrences (observed 2026-10-12: re-processing is outside the M5 scope, see
`docs/plans/M5_PLAN.md`).

## 5. Change it

Change the contract and let the tests object. Run on 2026-10-12: change `@router.post("/sources/{source_id}/process",
status_code=202)` to `status_code=200` and run `tests/integration/test_api_processing_routes.py`: it fails at
`test_processing_a_source_is_accepted_tracked_and_completed` because the response is `200`, not `202`. The `202` is
part of the API contract (the work happens later), and the front end relies on it. Restore the file.
The listing/paging behaviour is pinned by `test_runs_are_paged_by_cursor_and_the_cursor_is_bound_to_the_query` and
`test_runs_created_at_the_same_instant_are_paged_without_loss_or_repeats`: if you change an ordering, keep a unique
tie-breaker (`created_at.desc(), id.desc()`).

## 6. Break it on purpose

Process a source whose original is `MISSING` (see [storage](../../../02-data-and-storage/08-storage-roots-and-artifacts.md)):
`409 SOURCE_NOT_PROCESSABLE`. Process an id that does not exist: `404`. Start the real profile with no model package:
`POST .../process` answers `503 PROCESSING_UNAVAILABLE` and the backend's `/readiness` says `DEGRADED`
(`tests/integration/test_real_profile.py`; not run by hand here: no models). In every case no job is created.

## 7. Exercises

1. Why does `process` answer `202` and not `200`?
2. What is the relationship between a Job and a ProcessingRun?
3. Which runs can be retried, and what does retry create?
4. What does `policy.automatic_matching: false` mean for what the screen shows?
5. Which events does one successful processing publish?

**Answers**

1. Nothing has been recognised yet; the work is queued and happens in the background.
2. The Job is the scheduling record (priority, lease, attempts); the run is the history of one processing with its
   frozen settings. One request makes one of each.
3. `FAILED`, `INTERRUPTED`, `NOT_RESUMABLE`; a new Job and a new run linked by `parent_run_id`.
4. The policy can never match a face to an existing identity; the interface says "Automatic matching disabled".
5. `processing_run.created`, then `processing_run.updated` for `RUNNING` and for `COMPLETED`.

## 8. Related files

- Previous: [sources](sources.md) · Next: [jobs](jobs.md) · [Routes index](README.md)
- [Jobs and runs](../../processing/01-jobs-and-runs.md), [cancel and retry](../../processing/05-cancel-and-retry.md)
- [`backend/api/routes/processing.py`](../../../../../backend/api/routes/processing.py)
