# M2: Job repository

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-022, partly: the Job repository)
- **Status:** done for `jobs`; the other repositories in persistence §26 are not started
- **Commits:** [PR 26](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/26): `feat(jobs): add the
  job repository`, `test(jobs): add the job repository contract tests`, `docs: record the job
  repository`; the review fixes are folded into them (see Review)

## What changed

- `backend/app/jobs/repository.py`: `JobRepository(session)` with `add`, `get`, `claim_next`,
  `transition`, `set_progress` and `transient`, and the value `ClaimedJob`. It also now owns
  `FINISHED_JOB_STATES` (moved from `recovery/startup.py`, which imports it) and
  `LEASED_JOB_STATES`.
- `tests/integration/test_job_repository.py` (23 tests) against real SQLite, with separate sessions
  and threads.

## Why

TST-022 asks for repository contract tests that verify "real SQLite behaviour". Nothing in the
backend was a repository yet: use cases and the storage code build their own statements. The spec
(persistence §26) lists narrow repositories, and `Job` is the one whose contract depends most on the
database: an atomic claim. Others are added when a use case needs them rather than all at once
(`scope.md`: no abstractions the task does not need), so TST-022 stays open.

## Decisions

- **Repositories join the caller's transaction and never commit** (API and Contracts §103;
  persistence §26). Persistence §15 says a claim ends with "commit"; read with §26, the commit is
  the caller's. A claim that is never committed is rolled back with its transaction and the job is
  still `QUEUED` (tested). This is an interpretation, not a conflict that changes behaviour.
- **The "first statement is a write" guarantee has a limit, now stated and tested.** It holds only
  when the caller has not read in the same transaction. One that has, and then loses a race to
  another writer's commit, gets SQLite's `SQLITE_BUSY_SNAPSHOT` (an `OperationalError`) at once.
  That is CONTEXT open question 20 (`BEGIN IMMEDIATE` plus a whole-transaction retry, the unit of
  work's job), which the user owns; the repository neither retries nor settles it.
- **A claim is one `UPDATE ... RETURNING`**, its row chosen by a subquery ordered by priority rank,
  `created_at`, then `id`. The choice and the transition cannot be separated by another writer, the
  transaction's first statement is a write (no stale read snapshot), and the order is total. Four
  threads claiming 24 jobs get each exactly once. An outer `state = QUEUED` condition was tried and
  deleted: mutating it changed nothing, since the subquery already selects only `QUEUED` rows.
- **`claim_next` sets `started_at`.** A retry is a new Job linked by `previous_job_id` (§15), so a
  claimed job has not started before; there is no requeue path to preserve an earlier start for.
- **`transition(job_id, from_states, to_state)` leaves the rules to the caller, except that `RUNNING`
  is never a target** (`ValueError`): a running job must have the lease and heartbeat only
  `claim_next` records, so a transition cannot create a running, unleased job. A resume of a
  `PAUSED` job gets its own method when that use case exists. Which moves are
  legal is use-case policy (`repositories ... do not decide business truth`), so the repository
  guards only the states the caller names. Leaving the states a worker holds (`RUNNING`, `PAUSING`,
  `CANCELLING`) clears the lease and heartbeat; entering `COMPLETED`, `FAILED` or `CANCELLED`
  records `ended_at`.
- **`get` and `transient` re-read** (`populate_existing`), so a session that cached a row does not
  report a state another writer has since changed.
- **`INTERRUPTED` counts as transient**, as it already does for the startup workspace check (a job
  that is not over may resume).
- **Not built:** heartbeat/lease renewal, requeue of an interrupted job, and retry-as-new-job. The
  spec's minimum list for Job does not include them, and the policies (lease length, who requeues)
  belong to the scheduler.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 758 passed (23 new, 0 regressions in the 735
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 23 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 18 (priority, age and id in the claim
  order; the claim's lease, heartbeat and start time; the from-state guard; the `RUNNING` refusal;
  lease clearing and which states keep it; `ended_at` and which states end a job; failure code and
  detail; the finished-state filters in progress and the transient list; the transient order;
  `populate_existing`), all caught. Three survived at first and were fixed in the tests, not the code: the id tie-break (the tie-test jobs
  were inserted in id order, so insertion order hid it; they are now inserted in reverse), and
  `populate_existing` (the first test dropped its reference, so the session's weak identity map
  held nothing to be stale; it now holds it, with `expire_on_commit=False`). The fourth, the outer
  state condition, was deleted as above.
- **Not verified:** a repository for any table other than `jobs`; lease expiry and requeue.

## Review

Independent review by Codex CLI (`codex exec -s read-only`, disposable worktree): request changes,
five findings.

| Finding | Resolution |
|---|---|
| P1: a caller that read before `claim_next` can get `SQLITE_BUSY_SNAPSHOT` | Confirmed and now tested (a session that holds a snapshot loses to another claim and gets `OperationalError`). The "no stale snapshot" wording is corrected to the real, narrower guarantee. The fix, `BEGIN IMMEDIATE` and a whole-transaction retry, is open question 20, which the user owns, so it is not settled here |
| P1: `transition` could move a job to `RUNNING` with no lease | Fixed: `RUNNING` is refused (`ValueError`); only `claim_next` makes a job running. Tested, mutation-checked |
| P2: lifecycle and lease behaviour tested for one path only | Fixed: a table-driven test covers every target (`PAUSING` and `CANCELLING` keep the lease; `PAUSED`, `INTERRUPTED` and the three finished states clear it; only the finished ones set `ended_at`), plus a failure-recording test |
| P3: wrong spec section (§12.2, not §15) and a requeue rationale the spec does not support | Fixed. The speculative `coalesce(started_at)` was removed along with its test |
| P3: the entry listed a `test(jobs)` commit that did not exist, and the feature commit held the tests | Fixed: the unmerged branch was rebuilt as three commits (implementation, tests, docs) with the review fixes folded in, so the entry matches history |

## Correction (PR 27)

The threaded claim test above only started its threads together, which does not force them to
overlap: a claim that read before it wrote was caught by it in 1 of 5 runs. It now holds every
worker at its first `UPDATE` until all four have arrived (`tests/fixtures/concurrency.py`), and
that mutant is caught in 5 of 5.

## Open issues / follow-ups

- TST-022 continues with the other repositories in persistence §26, each when a use case needs it:
  ExecutionSegment/Checkpoint, IndexOperation (the coordinator builds its own statements today),
  Source, ProcessingRun. Representation's ann-key allocation waits for the user's decision on
  CONTEXT open question 21.
