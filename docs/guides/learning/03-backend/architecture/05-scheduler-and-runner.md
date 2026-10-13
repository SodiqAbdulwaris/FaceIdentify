# Architecture 05 The scheduler and the runner

## 1. What this is and why it exists

`POST .../process` only writes a request down. Someone has to *pick it up*. That someone is a small loop inside the
backend, the **scheduler service**, which keeps asking a **runner** "is there a queued job? do it". The split is
deliberate: the loop (`backend/api/scheduler.py`) knows about threads and waiting; the runner
(`backend/app/processing/runner.py`) knows about claiming, executing and accepting one job and deciding every outcome;
neither decides anything about identities. This lesson explains both and the guarantees that keep the library
consistent however a job ends.

## 2. Where it lives

| Piece | Where |
|---|---|
| The async loop | `SchedulerService` in `backend/api/scheduler.py` (`start`, `wake`, `stop`, `last_error`, `last_outcome`) |
| One unit of work | `ProcessingRunner.run_once` in `backend/app/processing/runner.py` |
| Claim and start | `ProcessingScheduler.claim_source_job` in `backend/app/processing/scheduler.py` |
| Execute | `ExecuteProcessingJob` in `backend/app/processing/execute_job.py` ([executing an image](../processing/03-executing-an-image.md)) |
| Accept | `AcceptProcessingRunUseCase` in `backend/app/processing/accept_run.py` ([acceptance](../processing/04-checkpoints-and-acceptance.md)) |
| Wiring | `Backend._boot` and `_run_once_for` in `backend/api/startup.py` |
| Tests | `tests/integration/test_api_scheduler.py`, `test_processing_runner.py`, `test_processing_scheduler.py` (24 tests) |

## 3. How it works

### The loop (`SchedulerService._run`)

```text
repeat until stopped:
    clear the wake flag                      # before the call: a wake that arrives meanwhile is kept
    outcome = run_once()  in a worker thread # blocking work must not block the event loop
    if the outcome was not IDLE: go round again at once (there may be more queued)
    else: wait until woken (a job was just queued) or idle_seconds (2.0) passes
```

- An error out of `run_once` is recorded by **class name** (`last_error`) and the loop waits one interval, so a
  persistent fault never spins at full speed; `/readiness` shows the scheduler `DEGRADED` while its last look failed.
- `stop()` lets the call in flight finish (it cannot be interrupted) and claims nothing more.
- The loop is created **only after the library has opened**, recovery included, so the two never race over a job.

### The runner (`ProcessingRunner.run_once`)

1. **Claim and start** in one short write transaction: the most urgent, oldest `QUEUED` job becomes `RUNNING` with a lease, its
   run begins, a lifecycle segment starts. A corrupt job is made `FAILED` rather than left leased forever.
2. **Execute** outside any write transaction (no ML under the database lock): decode, detect, embed, retrieve, decide,
   write *private* output, a `FINAL` checkpoint, run to `FINALIZING`.
3. **Accept** in one atomic transaction: the output becomes authoritative.
4. Every ending is decided:

   | Ending | Outcome kind | State left |
   |---|---|---|
   | nothing queued | `IDLE` | nothing |
   | accepted | `ACCEPTED` | run and job `COMPLETED` |
   | a failure the executor settled (`SETTLED_FAILURES`) | `FAILED` | run and job `FAILED`, output private |
   | a cancellation | `CANCELLED` | run and job `CANCELLED` |
   | a FINAL that acceptance refuses | `NOT_ACCEPTABLE` | run `NOT_RESUMABLE`, job `FAILED`, output private |
   | an error *after* acceptance committed (the index wake) | `ACCEPTED` with `wake_error` | `COMPLETED`; the durable index `ADD`s are replayed later |
   | anything else: a defect | raised as `RuntimeError`; the claimed work is settled `FAILED` best effort | never a half-state left behind |

   The runner is also told when a job starts (`on_started`) so the screen sees `RUNNING`; a failed notification never fails
   the work.
- **Priorities**: `INTERACTIVE` first, then `HIGH`, `NORMAL`, `LOW`, `MAINTENANCE`; ties by creation time then id
  (`priority_rank`).

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Watch the three states of one job: with the backend running, listen to events while you process
   ([call the API](../api/01-call-the-api.md), "Listen to events"). Observed:
   `processing_run.created {'state': 'PENDING'}`, `processing_run.updated {'state': 'RUNNING'}`, `processing_run.updated {'state': 'COMPLETED'}`.
   Those are the job being queued, claimed (`on_started`), and accepted (`run_once` returns).
2. Run the tests that pin every ending:

   ```bash
   uv run pytest tests/integration/test_processing_runner.py tests/integration/test_processing_scheduler.py tests/integration/test_api_scheduler.py -q
   ```

   Expected: `24 passed` (observed). Read the test names in `test_processing_runner.py`: `test_with_nothing_queued_the_runner_is_idle`,
   `test_a_queued_job_is_executed_accepted_and_indexed`, `test_a_failure_the_executor_settles_is_reported_and_leaves_private_output`,
   `test_a_cancellation_requested_during_work_ends_cancelled`, `test_a_refused_final_makes_the_run_not_resumable_and_the_job_failed`,
   `test_a_wake_error_after_the_commit_is_reported_and_the_run_stays_accepted`, ... one per row of the table.
3. See the loop's idle poll in the code: `grep -n "idle_seconds=" backend/api/development.py backend/api/real.py` shows
   `idle_seconds=2.0` and `lease_for=timedelta(minutes=10)`.
4. See what the scheduler reports in `/readiness`: `"scheduler":"READY"` while its loop runs; `STOPPED` after `stop`;
   `DEGRADED` while its last look failed (`Backend.readiness`).

## 5. Change it

The loop's properties are testable without waiting because the tests inject `run_once` and use the explicit `wake()` with a
long idle interval (no `sleep` coordination; see the 2026-10-07 implementation entry on the scheduler-degrade test race).
To change how the runner ends a failure, add the case to the table, write the test first in `test_processing_runner.py` with
the `pipeline` fixture (`tests/fixtures/pipeline.py`: a real library, planted perception), then change `run_once`. Never
add a retry loop around `run_once`: a defect must not be retried blindly (the docstring says so); the user's explicit
retry is a *new* job ([cancel and retry](../processing/05-cancel-and-retry.md)).

## 6. Break it on purpose

Make `run_once` raise inside the loop (the tests do this with a fake): `/readiness` shows `"scheduler":"DEGRADED"` and
`last_error` holds only the exception class name; the loop sleeps one interval and tries again, so the process neither dies
nor spins. Stop the scheduler while a job is running: `stop()` waits for the call to finish.

## 7. Exercises

1. Why does the loop clear the wake flag *before* calling `run_once`?
2. Why does the runner execute outside a write transaction?
3. What state is a run left in if acceptance refuses its FINAL checkpoint?
4. Why is the scheduler created after the library opens?

**Answers**

1. A job queued while `run_once` is running sets the flag again; clearing afterwards would lose that wake.
2. A slow model call must not hold SQLite's one write lock.
3. `NOT_RESUMABLE`, with the job `FAILED` and the output kept private.
4. Startup recovery must finish first, so it and the loop never race over the same job or run.

## 8. Related files

- Previous: [04 Profiles](04-profiles.md) · Next: [06 Recovery](06-recovery.md)
- [`backend/api/scheduler.py`](../../../../../backend/api/scheduler.py), [`backend/app/processing/runner.py`](../../../../../backend/app/processing/runner.py)
- [Jobs and runs](../processing/01-jobs-and-runs.md)
