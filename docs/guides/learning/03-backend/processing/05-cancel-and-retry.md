# Processing 05 Cancel and retry

## 1. What this is and why it exists

Users stop work and repeat it. **Cancel** asks a run to stop, safely, at any moment. **Retry** starts a failed or interrupted
attempt again as a *new* job and run, never by resetting the old one, so the history of what happened stays intact.

## 2. Where it lives

| Thing | Where |
|---|---|
| Cancel | `backend/app/processing/cancel.py`; routes `POST /processing-runs/{id}/cancel`, `POST /jobs/{id}/cancel` |
| Retry | `RetryProcessingUseCase` in `backend/app/processing/retry.py`; route `POST /processing-runs/{id}/retry` (202) |
| The executor's observation of a request | `_cancel_if_requested`, `_cancel` in `execute_job.py` |
| Tests | `tests/integration/test_cancel_processing.py` (7), `test_api_processing_routes.py`, `test_api_jobs.py` |

## 3. How it works

**Cancel** writes the *request* in one transaction that takes the run's write lock first:

| Run is | Result |
|---|---|
| queued (`PENDING`) | job and run `CANCELLED` at once; the scheduler never claims it |
| running | job and run `CANCELLING`; the executor settles `CANCELLED` at its next safe boundary; its private output stays private |
| already `CANCELLING` or `CANCELLED` | nothing changes (a double click is safe) |
| `FINALIZING`, finished, paused, interrupted, or with no job | refused: `409` ([jobs routes](../api/routes/jobs.md)) |

The executor never writes the request; only the use case does. A crash during `CANCELLING` is settled `CANCELLED` by recovery.

**Retry** (`RetryProcessingUseCase`): for a failed or interrupted attempt, create a **new** job (`previous_job_id` set, the
next `attempt_number`) and a **new** run (`parent_run_id` set) that freezes a *copy* of the old snapshot. The old run keeps
its state and its private output; recovery never re-queues anything by itself.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_cancel_processing.py tests/integration/test_api_processing_routes.py -q
```

Expected: pass. Names to read in `test_cancel_processing.py`: `test_a_queued_run_is_cancelled_at_once_and_never_claimed`,
`test_a_repeated_cancel_changes_nothing`, `test_a_running_run_is_asked_to_stop_and_settles_cancelled_with_private_output`,
`test_a_run_that_is_being_made_authoritative_cannot_be_cancelled`. On the development profile a job takes about 80 ms, so a
cancel by hand almost always meets a finished run: curl it anyway and read the `409 RUN_NOT_CANCELLABLE` reason
(`run ... is COMPLETED, which cannot be cancelled`; shown in the [jobs lesson](../api/routes/jobs.md)).

## 5. Change it

To allow cancelling in another state, write the failing test first in `test_cancel_processing.py`, change the transition table
in `cancel.py`, and update the table above and the route's documented errors. Cancelling `FINALIZING` is refused on purpose:
acceptance is about to commit.

## 6. Break it on purpose

Make the repeated-cancel branch raise instead of doing nothing (scratch edit): `test_a_repeated_cancel_changes_nothing` fails.
Restore with `git restore`.

## 7. Exercises

1. Why does a retry create a new run instead of resetting the old one?
2. When is a cancel immediate, and when is it a request?
3. Why can't a `FINALIZING` run be cancelled?
4. What does the new run's snapshot come from?

**Answers**

1. The old attempt's history and private output must stay exactly as they ended.
2. Immediate for a queued run; a request (`CANCELLING`) for a running one.
3. Its result is being made authoritative; stopping now would race the commit.
4. A copy of the old run's snapshot.

## 8. Related files

- Previous: [04](04-checkpoints-and-acceptance.md) · Up: [Processing](README.md)
- [`backend/app/processing/cancel.py`](../../../../../backend/app/processing/cancel.py), [`retry.py`](../../../../../backend/app/processing/retry.py)
