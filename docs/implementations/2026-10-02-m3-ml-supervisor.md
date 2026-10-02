# M3: the ML supervisor (step 5b, second half; TST-035 passing)

Date: 2026-10-02. Spec: API and Contracts sections 47 to 50 (policy recorded as a dated note after section 50).

## What was built
- `backend/ml/supervisor/supervisor.py`: `MLSupervisor(spawn, policy, clock)` with `start`, `execute`, `release_output`, `ping`, `stop`, `reset` and the states STOPPED, STARTING, READY, BUSY, STOPPING, UNAVAILABLE, FAILED. `SupervisorPolicy` (handshake, request, ping and shutdown timeouts, `max_restarts`, `restart_window`; none has a default). Errors: `WorkerFailedError` (the worker died, timed out or broke the protocol) and `MLUnavailableError` (the capability has FAILED).
- `backend/ml/supervisor/process.py`: `ProcessWorker` (a `spawn` child reached over a pipe, killed with its whole process tree on Windows) and `kill_process_tree`.
- `backend/ml/worker/main.py`: the child's entry point; `load_handlers("module:function")` builds the handlers inside the worker so the supervising process never imports a model library.

## Behaviour pinned by the tests (real worker processes)
An ERROR response is returned and changes nothing; a worker killed between requests is replaced by the next call; a worker that dies or times out during a request is killed and the call raises `WorkerFailedError` (the caller's own segments are untouched, the next call starts a new worker); a worker that cannot load its models fails every start until more than `max_restarts` failures inside the window make a crash loop (`FAILED`: nothing more is started, only `reset()` allows another try, stopping does not forgive it); failures further apart than the window never accumulate; a worker that never becomes ready is killed; a worker whose parent is killed ends itself; protocol breaks by a scripted worker (a response to another request, garbage, a wrong PONG, a handshake that is not HELLO) are failures; `stop()` asks first and kills only if there is no acknowledgement.

## A bug the tests found
`TimeoutError` is a subclass of `OSError`, so an `except (OSError, EOFError)` placed before `except TimeoutError` reported every timeout as "the worker died". Fixed by ordering the clauses and pinned by the timeout and handshake-timeout tests.

## Verification
33 supervisor tests (about 100 seconds: real processes) and 6 for loading handlers. 38 mutations of the supervisor and the process handle; the 4 survivors led to three new tests (successive pings use different nonces, killing closes the pipe, a stop is a graceful SHUTDOWN first) and one deletion (a `join` that is not needed after `taskkill`). One survivor is documented, not tested: closing the parent's copy of the child's pipe end matters on POSIX (otherwise the child's death is never seen) but Windows pipes break either way.
