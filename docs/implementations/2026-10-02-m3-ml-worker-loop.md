# M3: the ML worker loop (step 5b, first half of TST-035)

Date: 2026-10-02. Spec: API and Contracts sections 35 to 50. The supervisor and the real-process tests are the second half.

## What was built
- `backend/ml/worker/loop.py`: `serve(connection, handlers, instance_id, new_id, clock)` runs the whole worker protocol (see the dated note in API and Contracts after section 49). `Handler`, `HandlerContext` (the ledger a handler creates result segments in), `HandlerResult` and `WorkerError` (a failure with a chosen code). It knows nothing of any model: handlers are passed in.
- `error_wire` (contracts): an ERROR response for a request that never parsed, so it can still be answered under its id.
- `tests/fixtures/ml_handlers.py`: fake detector and embedder handlers with failure modes (raise, out of memory, coded error, hang, sleep, exit) for the worker and supervisor tests.

## Behaviour pinned by the tests
Every request is answered once; a handler failure, a bad request and a missing handler never stop the worker; a result's segments live until its RELEASE_OUTPUT; a failed request releases its own segments and never another request's; the same request id used twice is released together; SHUTDOWN is acknowledged; a vanished parent, a frame the worker cannot follow and SHUTDOWN all release everything the worker owns, by an explicit release (checked with a spy, because garbage collection would otherwise hide a missing one).

## Verification
32 tests of the loop (run in a thread over a real pipe, so they are measured), a test of `error_wire`, 23 mutations of the loop all caught, loop tests repeated five times. One dictionary-hygiene detail is not observable and was left as is (the entry for a released request is dropped from the worker's map).
