# Processing 01 Jobs and runs

## 1. What this is and why it exists

"Process this picture" creates **three records** because they answer different questions:

- a **processing run**: *what is being done to this source, with which settings, and what came of it* (the history);
- a **job**: *schedulable work*: its priority, its lease, who is doing it (the machinery);
- an **execution segment**: *one continuous stretch of executing* the run, with the runtime used (the provenance).

A run can outlive its job; a retry is a new job and a new run. Keeping them apart is what makes recovery and retries honest.

## 2. Where it lives

| Thing | Where |
|---|---|
| `Job`, `JobState`, `JobPriority`, `JobType` | `backend/app/jobs/models.py` |
| `ProcessingRun`, `ProcessingRunState`, `ExecutionSegment`, `ProcessingCheckpoint` | `backend/app/processing/models.py` |
| The request | `ProcessSourceUseCase` in `backend/app/processing/process_source.py` |
| Repositories | `backend/app/jobs/repository.py`, `run_repository.py` |
| Claiming | `ProcessingScheduler` in `backend/app/processing/scheduler.py` |
| Tests | `tests/integration/test_process_source.py`, `test_processing_scheduler.py`, `test_processing_run_repository.py` |

## 3. How it works

- **Request** (`POST /sources/{id}/process`): in one transaction, resolve and freeze the settings
  ([snapshots](02-configuration-snapshots.md)), create a run (`PENDING`) and a `PROCESS_SOURCE` job (`QUEUED`, priority
  `INTERACTIVE`), and point the source at the run. A source that cannot be processed leaves **no rows** behind.
- **Job states**: `QUEUED`, `RUNNING`, `PAUSING`, `PAUSED`, `CANCELLING`, `CANCELLED`, `COMPLETED`, `FAILED`, `INTERRUPTED`.
- **Run states**: `PENDING`, `RUNNING`, `PAUSING`, `PAUSED`, `CANCELLING`, `CANCELLED`, `FINALIZING`, `COMPLETED`, `FAILED`
  (and the recovery states `INTERRUPTED` and `NOT_RESUMABLE` described in [recovery](../architecture/06-recovery.md)).
  `FINALIZING` is special: the work is done and its FINAL result is being made authoritative.
- **Priority** is stored both as a word and as an integer `priority_rank` (the claim orders by the integer, because
  ordering the words alphabetically would put `HIGH` before `INTERACTIVE`).
- **Lease**: a claimed job records `lease_owner` and `lease_expires_at` (ten minutes) and a `heartbeat_at`, so a dead worker
  cannot hold work forever. `attempt_number` and `previous_job_id` record retries.
- **Segment**: starting a run starts segment `ordinal` 0, `RUNNING`, and ends with an `end_reason`
  (`NORMAL`, `FALLBACK`, `CUDA_OOM`, `WORKER_CRASH`, `CANCELLED`, `SHUTDOWN`). A provider fallback ends one segment and starts the next.
- Every state change is a **guarded transition** (`UPDATE ... WHERE state = ...`) and bumps `revision`.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([domain README](../domain/README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select type, state, priority, priority_rank, progress_mode, attempt_number, previous_job_id is null, lease_owner is null, started_at is not null, ended_at is not null from jobs" "select state, parent_run_id is null, current_checkpoint_id is not null, revision from processing_runs" "select ordinal, state, ended_reason from execution_segments"
```

Observed (each of three rows): `('PROCESS_SOURCE', 'COMPLETED', 'INTERACTIVE', 0, 'INDETERMINATE', 1, 1, 1, 1, 1)`: a finished job holds no lease,
is the first attempt, and has start and end times; the run `('COMPLETED', 1, 1, 5)`: no parent, a current checkpoint, revision 5
(each transition added one); the segment `(0, 'COMPLETED', 'NORMAL')`. Then watch the transitions live with the event listener in
[call the API](../api/01-call-the-api.md): `PENDING`, `RUNNING`, `COMPLETED`.

## 5. Change it

A new job type needs: an enum value (plus a migration: the type list is a database check), a use case that creates the run/job
pair, an executor, and a branch in the runner. Do the read-only version first: find where `PROCESS_SOURCE` is claimed
(`claim_source_job`) and list which parts are specific to images.

## 6. Break it on purpose

Move a source to the recycle bin (`POST .../recycle`, [sources routes](../api/routes/sources.md)) and ask to process it: the
request is refused with `409 SOURCE_NOT_PROCESSABLE` and the reason "is not active", and **no run, job or snapshot is
created** (`require_processable_image`; `test_unprocessable_source_leaves_no_snapshot_run_or_job`). *The 409 and its code were read
from `backend/api/routes/processing.py` and the test, not curled in this session.*

## 7. Exercises

1. Why are the run and the job separate?
2. What does `attempt_number` plus `previous_job_id` express?
3. Why is `priority_rank` an integer?
4. What is a segment for?

**Answers**

1. The run is history and settings; the job is schedulable machinery. A retry makes new ones; the old run stays as it ended.
2. A retry chain: this job is attempt N of the one named by `previous_job_id`.
3. Words sort alphabetically, not by urgency.
4. To record which runtime actually executed which stretch, including fallbacks and crashes.

## 8. Related files

- Next: [02 Configuration snapshots](02-configuration-snapshots.md)
- [`backend/app/jobs/models.py`](../../../../backend/app/jobs/models.py), [`backend/app/processing/models.py`](../../../../backend/app/processing/models.py)
