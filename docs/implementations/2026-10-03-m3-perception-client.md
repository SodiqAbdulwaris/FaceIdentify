# M3: the backend client for perception (step 7, fifth part)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 · TST-038, TST-039 (in progress)
- **Status:** done as the client part of step 7. The PENDING-output writer subsequently landed in PR #96 after revision `0005`.
- **Commits:** PR (this branch): `feat(runtime): run a perception plan against the ML worker`

## What changed
- `backend/app/runtime/perception_client.py`: `PerceptionClient(supervisor, plan, *, new_id)` with `detect(pixels, context=None) -> Detected(detections, ran)` and `represent(pixels, detections, context=None) -> Represented(vectors, ran)`. `supervisor_for(plan, policy)` builds an `MLSupervisor` whose worker is started with `plan.worker_config()`.
- **Fallback is the backend's, and narrow.** Only `RUNTIME_VARIANT_NOT_AVAILABLE` and `RUNTIME_INITIALIZATION_FAILED` (this provider cannot run here) move on to the next planned variant, in the caller's order. Every other error (`COMPONENT_LOAD_FAILED`, `INVALID_INPUT`, `INFERENCE_FAILED`, ...) is raised as `PerceptionError(code, message)`, because trying another variant would hide it. When every variant of a stage is ruled out the answer is `RuntimeUnavailableError` with one reason per variant (the same exception the plan raises), never a substitute.
- A ruled-out variant stays out for the life of the client, so one run does not bounce between providers.
- **`ran` is the variant that actually executed** (the `PlannedVariant`, with its `runtime_variant_id` and component version), and it is checked against the worker's own provenance: an answer naming another variant or component is refused and its outputs released, never recorded under the variant that was asked for. This is the value the writer stores in `runtime_variant_id` (issue 88).
- Pixels travel in a segment the client creates and releases around the call (`SegmentLedger`, either way); vectors are copied out of the worker's segments (canonical little-endian float32) and the outputs are released with `release_output`, also when reading them fails. The answer must be for exactly the faces asked about, each once, with the plan's dimension and `float32`.
- No faces is a result (empty `detections`, `ran` says which detector looked); with nothing to represent no worker call is made (`ran` is `None`).
- The ruled-out record is per stage (a variant ruled out for the detector is still asked for the embedder), `represent` refuses a repeated detection index before any call, and a client belongs to one thread (one processing run): its record is not locked and releasing an output is a separate call from the request.
- A failing worker (dead, timed out) is the supervisor's `WorkerFailedError`, unchanged: nothing is retried here; the caller decides.

## Decisions (the agent's)
- The client lives in `backend/app/runtime/` beside the plan it consumes; it is the first place the backend imports the worker's contract (messages and supervisor), which it must, because it is the other end of that protocol.
- `represent` takes the `Detection`s from `detect` (their normalised box and landmarks go to the worker as the face geometry); a detection without landmarks is the worker's to refuse (`INVALID_INPUT`).
- The `normalization` of each vector is returned with it; the writer compares it with the space's, so the plan did not need to carry it.
- Not built: a way to forgive a ruled-out variant within one client (a new client or a new run decides again); retry of a request after a worker failure.

## Verification
- `tests/integration/test_runtime_perception_client.py` (33 tests, 100% coverage of the module): see the tracker row. Four tests use a real worker process with generated ONNX models; the rest script the supervisor to reach answers a real worker cannot be made to give (an initialisation failure, an answer for the wrong variant or faces).
- Mutation pass: 22 mutations (every guard, the provider-code set both ways, the ruled-out record, the provenance check, the answer checks, the release of outputs, the context); one survivor on the first run (the execution context was never observed) led to a test; none survive.
- Full gate: see the PR.

## Open issues / follow-ups
- The PENDING-output writer (after migration 0005; issue 88) is in PR #96.
- Steps 8 and 9 (the run-local index, retrieval, recognition) need no output rows and come next.
