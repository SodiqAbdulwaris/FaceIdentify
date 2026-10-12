# Architecture 06 Recovery: surviving being killed

## 1. What this is and why it exists

The program is allowed to be killed at any moment: power loss, a crash, Task Manager. The design makes that safe with
four tools used together: **atomic writes** and **transactions** (a change is all or nothing), **durable intent records**
(job and run states, index operations, the erasure marker) written *before* the side effect they describe, and
**startup recovery**, which runs when the library opens and *before the scheduler starts*, looks at what was left half done
and settles it. It is **idempotent** (running it twice equals once) and is tested by killing real processes.

## 2. Where it lives

| Thing | Where |
|---|---|
| Recovery | `recover_on_startup` in `backend/app/recovery/startup.py`; the report (`StartupReport`) |
| When it runs | `open_library` in `backend/app/lifecycle.py`, after the lock, migrations and layout |
| The report to readiness | `capabilities_from` in `backend/api/startup.py` |
| Interrupted deletions | `PermanentSourceDeletion.resume` (called from `Backend._open`) |
| Tests that kill real processes | `tests/recovery/test_process_kill.py`, `test_pipeline_process_kill.py`, `test_cross_storage_failures.py`, `test_finalizing_recovery.py`, `test_missing_managed_files.py`, `test_startup_recovery.py` |
| Spec | `docs/specs/PERSISTENCE_IMPLEMENTATION.md` section 28; `IMPLEMENTATION_ARCHITECTURE.md` section 23 |

## 3. How it works

Startup order is database and migrations, storage, **recovery**, **indexes**, then the profile's preparation, then the
scheduler. Recovery does, in order:

1. **Artifacts**: settle every interrupted managed write and deletion; mark an available managed artifact or a
   referenced original whose file is gone `MISSING` (existence only: nothing is hashed at startup).
2. **In-flight work**: a `RUNNING` job, run or segment belongs to a process that no longer exists, so it becomes
   **`INTERRUPTED`** and the lease is cleared (never silently re-queued; a retry is an explicit *new* job). A job or run
   found `PAUSING` becomes `PAUSED`; one found `CANCELLING` becomes `CANCELLED`.
3. **`FINALIZING` runs**: a run whose valid `FINAL` checkpoint exists is **accepted without running any ML**. A `FINAL`
   that acceptance refuses leaves the run `NOT_RESUMABLE`, its output private.
4. **Workspaces**: remove the temporary folder of every finished job; keep those a job may resume.
5. **Indexes**: validate each space's index and rebuild what is missing, corrupt or stale; give `FAILED` index
   operations one fresh set of attempts; catch pending operations up in bounded passes.
6. **Erasures**: every `ERASING` representation is finished if its conditions hold; an owed log truncation is done;
   whatever cannot finish is reported as *unresolved*.

The recovery guarantees by crash point (all tested): a crash **before** the `FINAL` checkpoint leaves the run
`INTERRUPTED` with its `PENDING` output kept private and nothing re-queued; a crash **after** `FINAL` but before
acceptance is accepted exactly once at the next start without ML; a crash **after** acceptance leaves only the index to
converge (the `ADD` operations are replayed). Output is *never* visible before acceptance, so a crash can never show half a
result.

What recovery relies on: **one process, no other user of the library** (the library lock guarantees it) and that nothing in
memory survived. The result is a report; anything it could not settle becomes a `DEGRADED` capability in `/readiness`, not a
silent hope.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. **Kill it hard and see nothing is lost.** With a backend running on a library that has data, find its `pid` (the handshake
   line) and, on Linux or macOS, `kill -9 <pid>` (on Windows, end the task in Task Manager, or `taskkill /F /PID <pid>`;
   *unverified here*). Look at the folder: `library.db-wal` is still there (a clean stop would have merged and removed
   it). Start the backend again with the same folders:

   ```bash
   curl -s -H "$H" $B/readiness
   curl -s -H "$H" "$B/api/v1/sources?limit=50" | j "len(d['items'])"
   ```

   Observed: the new backend answers `{"state":"READY",...}` and the same number of sources as before the kill (6 and 6).
   The operating system freed the library lock when the process died, the write-ahead log was replayed by SQLite, and
   recovery found nothing to repair.
2. **Run the process-kill tests.** They start a real backend child, kill it at chosen points and restart:

   ```bash
   uv run pytest tests/recovery -q
   ```

   Expected on Linux: `164 passed, 1 failed` (observed; the one failure is `test_an_erasure_that_cannot_finish_is_reported_unresolved_not_clean`,
   which relies on a Windows file lock). On Windows, all pass. The three kill tests that matter most:
   `test_pipeline_process_kill.py::test_a_crash_before_final_is_interrupted_private_and_redone_as_a_retry`,
   `::test_a_crash_after_final_is_accepted_once_on_the_next_start_without_ml`,
   `::test_a_crash_after_acceptance_leaves_only_the_index_to_converge`.
3. **Read the report.** The fields of `StartupReport` (`backend/app/recovery/startup.py`) are the vocabulary:
   `artifacts`, `missing_references`, `missing_managed`, `interrupted`, `workspaces`, `indexes_rebuilt`,
   `requeued_operations`, `index_operations`, `index_passes`, `erasure`, `packages`, `finalizing`; and the properties
   `unresolved` (what it tried and could not finish, by name, e.g. "2 erasure steps outstanding"), `repaired_nothing`
   and `clean` (`test_a_report_with_no_repairs_says_so`, `test_unresolved_work_means_the_run_is_not_clean`).
4. **Corrupt the index and restart** ([vector index lesson](../../02-data-and-storage/06-vector-index-and-outbox.md)): the
   index is quarantined and rebuilt; the backend is `READY`.

## 5. Change it

Recovery is easy to break and the tests are strong, so the rule is: **write the crash test first**. To add a recovery step,
add a case to `tests/recovery/test_startup_recovery.py` (it has helpers that stage an interrupted state and run recovery
twice to prove idempotence: `test_a_second_run_finds_nothing_and_changes_nothing`,
`test_a_crash_after_any_step_is_repaired_by_running_recovery_again`), then implement the step so it is a *guarded
transition* (an `UPDATE ... WHERE state = ...`), then record it in the report. Never make recovery re-run ML, re-queue a
job, or turn a pending run's output into memory.

## 6. Break it on purpose

Remove the `INTERRUPTED` step from your reading of `startup.py` mentally: a job stuck `RUNNING` forever would hold its
lease and the source would show "Processing" forever. That is the failure the step prevents. By hand, a *lesser* version:
kill the backend at the instant a job is running (hard to time on the development profile, where a job takes about 80 ms;
`test_a_backend_killed_while_it_ran_a_job_is_recovered_on_the_next_start` does it with a child process that starts a job and is then killed) and look at
`select state from processing_runs`: `INTERRUPTED` after the restart, never `RUNNING`.

## 7. Exercises

1. What happens to a run that was `RUNNING` when the program was killed?
2. Why is `FINAL` accepted at startup *without* re-running the models?
3. Why does recovery run before the scheduler starts?
4. What does a `DEGRADED` `recovery` capability tell you?
5. What does "idempotent" mean for recovery, and which test shows it?

**Answers**

1. `INTERRUPTED`; its partial output stays private; a retry is a new job.
2. The `FINAL` checkpoint holds the complete decision evidence, so acceptance can complete exactly once without new inference.
3. Otherwise the loop could claim a job recovery is repairing.
4. Something recoverable is outstanding (an erasure cleanup, an invalid package); it is retried at the next start.
5. Running it twice gives the same result as once; `test_a_second_run_finds_nothing_and_changes_nothing`.

## 8. Related files

- Previous: [05 The scheduler and runner](05-scheduler-and-runner.md) · Next: [07 Events](07-events.md)
- [`backend/app/recovery/startup.py`](../../../../backend/app/recovery/startup.py)
- [Checkpoints and acceptance](../processing/04-checkpoints-and-acceptance.md), [erasure](../../02-data-and-storage/07-erasure.md)
