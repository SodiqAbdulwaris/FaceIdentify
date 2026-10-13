# Runtime 02 The supervisor

## 1. What this is and why it exists

A process that loads multi-gigabyte models will sometimes die, hang or run out of memory. The **supervisor**
(`MLSupervisor`) owns the worker process: it starts it, waits for `READY`, sends one request at a time, notices failure, kills
what is stuck, and starts a fresh worker for the next call, but only a bounded number of times, so a broken model becomes a
clear `FAILED` state instead of a restart loop.

## 2. Where it lives

| Thing | Where |
|---|---|
| `MLSupervisor`, `SupervisorPolicy`, `WorkerFailedError`, `MLUnavailableError` | `backend/ml/supervisor/supervisor.py` |
| Starting and killing the real process | `backend/ml/supervisor/process.py` |
| Where the backend sets the limits | `WORKER_POLICY` in `backend/api/real.py`; `ClientPool` keeps one supervisor per plan |
| Tests | `tests/integration/test_ml_supervisor.py` (runs on Windows; see below) |

## 3. How it works

- **Three kinds of failure, kept apart.** An `ERROR` response is an operation failure (returned, nothing else changes). A
  response saying a component or runtime cannot run is returned for the *backend* to decide about fallback. Only the worker
  *itself* failing (died, timed out, spoke nonsense) is the supervisor's: it kills the process, the state becomes
  `UNAVAILABLE`, and the caller gets `WorkerFailedError`.
- **States**: `STOPPED`, `STARTING`, `READY`, `BUSY`, `STOPPING`, `UNAVAILABLE`, `FAILED`.
- **Restart policy** (`SupervisorPolicy`, no defaults: the caller's measured choices): `handshake_timeout`, `request_timeout`,
  `ping_timeout`, `shutdown_timeout`, `max_restarts` and `restart_window`. More than `max_restarts` failures inside the window is a
  crash loop: the capability is `FAILED` until `reset()` (a deliberate act). The real profile uses
  `SupervisorPolicy(120, 120, 10, 10, 1, 600)`, provisional because nothing has measured them (the first model load takes seconds).
- **One request at a time** (a lock). A request in flight when the worker dies is **never retried here**; the caller decides.
- **A request is sent only to a worker just seen to be alive.**
- **Shared memory ownership**: the caller owns segments it passed in and releases them after the response (or when this raises);
  the worker owns its result segments, freed by the operating system if it dies, otherwise by `release_output`.
- **Windows detail**: the interpreter a virtual environment starts may itself start the real one, so a worker is killed with its
  whole process tree (`process.py`). That is also why the supervisor tests use `tasklist`.

## 4. Try it

**Needs Windows to run the real-process tests. Unverified here.** On Linux this session saw the 11 tests of
`tests/integration/test_ml_supervisor.py` fail with `FileNotFoundError: 'tasklist'` (a Windows-only command); that is a platform
fact, not a defect in the supervisor. On Windows:

```bash
uv run pytest tests/integration/test_ml_supervisor.py -q
```

*Expected: pass (not run here).* Read the names: `test_a_worker_that_died_between_requests_is_replaced_by_the_next_call`,
`test_a_worker_that_dies_during_a_request_fails_it_and_corrupts_nothing`, `test_a_worker_that_does_not_answer_in_time_is_killed`,
`test_a_worker_found_dead_that_makes_a_crash_loop_is_refused_not_restarted`. They are the failure modes above, one each. The
logic that does not need a process (the policy validation) is covered by the client tests, which passed.

## 5. Change it

Changing a limit means changing `WORKER_POLICY` (or its profile equivalent) and measuring: the policy has no defaults on
purpose. A real change belongs with a benchmark note in `docs/implementations/`. Never add "retry the request" to
the supervisor; whether a request is safe to repeat is the caller's knowledge.

## 6. Break it on purpose

Set `max_restarts` to 0 (a scratch edit, tests only): the first worker failure makes the capability `FAILED`, and `/readiness`
shows `ml_worker` unhealthy until restart. Restore with `git restore`.

## 7. Exercises

1. What is the difference between an `ERROR` response and a `WorkerFailedError`?
2. Why is a failed request not retried by the supervisor?
3. What does `FAILED` mean and how does it end?
4. Why do the policy values have no defaults?

**Answers**

1. The first is the worker answering that an operation failed; the second is the worker itself failing (dead, silent, broken).
2. The caller knows whether repeating is safe; the supervisor does not.
3. A crash loop was detected; it ends only by `reset()` (a deliberate act) or a new process.
4. They must come from measurements; a default would hide that nobody measured.

## 8. Related files

- Previous: [01](01-worker-and-messages.md) · Next: [03 The perception client and providers](03-perception-client-and-providers.md)
- [`backend/ml/supervisor/supervisor.py`](../../../../../backend/ml/supervisor/supervisor.py)
