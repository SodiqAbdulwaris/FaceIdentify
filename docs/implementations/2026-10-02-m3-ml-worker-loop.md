# M3: the ML worker loop (step 5b, first half of TST-035)

Date: 2026-10-02. Spec: API and Contracts sections 35 to 50. The supervisor and the real-process tests are the second half.

## What was built
- `backend/ml/worker/loop.py`: `serve(connection, handlers, instance_id, new_id, clock)` runs the whole worker protocol (see the dated note in API and Contracts after section 49). `Handler`, `HandlerContext` (the ledger a handler creates result segments in), `HandlerResult` and `WorkerError` (a failure with a chosen code). It knows nothing of any model: handlers are passed in.
- `error_wire` (contracts): an ERROR response for a request that never parsed, so it can still be answered under its id.
- `tests/fixtures/ml_handlers.py`: fake detector and embedder handlers with failure modes (raise, out of memory, coded error, hang, sleep, exit) for the worker and supervisor tests.

## Behaviour pinned by the tests
Every request is answered once; a handler failure, a bad request and a missing handler never stop the worker; a result's segments live until its RELEASE_OUTPUT; a failed request releases its own segments and never another request's; the same request id used twice is released together; SHUTDOWN is acknowledged; a vanished parent, a frame the worker cannot follow and SHUTDOWN all release everything the worker owns, by an explicit release (checked with a spy, because garbage collection would otherwise hide a missing one).

## Verification
45 tests of the loop (run in a thread over a real pipe, so they are measured; the harness fails a test if anything escapes `serve`, so a crashed worker cannot pass as one that left), a test of `error_wire`, 36 mutations of the loop all caught, loop tests repeated. One dictionary-hygiene detail is not observable and was left as is (the entry for a released request is dropped from the worker's map).

## Review
OpenCode (`opencode/big-pickle`, plan agent, watchdog; about 11 minutes). One blocker, two majors, fixed: a write to a parent that had gone crashed the worker instead of ending it quietly (only reads were handled); answering was not total (a handler leaving a view open broke the failure path, a `WorkerError` with a bad code or a message that could not be printed raised inside the error path, `to_wire()` sat outside the try, and the final release could replace a real error); and the leave tests could not tell "left cleanly" from "crashed" (the thread swallowed the exception), so they would have passed on both bugs. Fixed with them: a handler's answer is checked against its request, an output is recorded only when something was made, every exit logs why, failure messages are cut to 500 characters, the third unreadable-request code and a second INITIALIZE are tested, workers are always closed and joined. Documented: the worker has no timeout of its own (the supervisor owns them), and a RESPONSE must be read before the RELEASE_OUTPUT that follows it.

Lesson, for the mutation procedure: run the unmutated suite first. A mutation result is meaningless over a failing baseline (one earlier run said "0 survivors" while the baseline failed because a deliberately leaked segment collided with the next test's deterministic id). A deliberately leaked resource must be handed back to the test to clean up.
