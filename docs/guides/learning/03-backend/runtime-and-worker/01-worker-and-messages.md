# Runtime 01 The worker and its messages

## 1. What this is and why it exists

Model libraries are large, can crash, can run out of GPU memory and take seconds to load. So they live in their own process
(`backend/ml/`), which has **no database and no application knowledge**: it detects faces and computes representations, nothing
else. The backend talks to it over a small, strict protocol. If the worker dies the application survives; if a model is
wrong, the damage is a coded error, not a corrupted library.

## 2. Where it lives

| Thing | Where |
|---|---|
| Protocol vocabulary (operations, status, error codes, worker states, control frames) | `backend/ml/contracts/protocol.py` |
| Requests and responses with their validation | `backend/ml/contracts/messages.py` (609 lines) |
| Control frames, strict wire readers, shared memory descriptors | `control.py`, `wire.py`, `shared_memory.py` |
| The worker's message loop | `backend/ml/worker/loop.py`; entry `main.py` |
| The two operations on ONNX models | `backend/ml/worker/perception_handlers.py`, `onnx_session.py`, `backend/ml/perception/` |
| Tests | `tests/contracts/test_ml_ipc_contract.py`, `tests/integration/test_ml_worker_loop.py`, `test_ml_perception_handlers.py` |
| Spec | `API and Contracts.md` sections 35 to 50 |

## 3. How it works

- **Two operations only**: `DETECT_FACES` and `GENERATE_REPRESENTATIONS`. Zero faces is a successful empty result, never an error.
- **Control frames** (plain JSON-compatible dicts over a `multiprocessing` connection, not pickled classes):
  `HELLO` → `INITIALIZE` → `READY`, then `EXECUTE`/`RESPONSE`, `RELEASE_OUTPUT`, `PING`/`PONG`, `SHUTDOWN`/`SHUTDOWN_ACK`.
- **Exactly one response per request**: `SUCCESS` or `ERROR` with a code from a fixed list: `INVALID_REQUEST`,
  `UNSUPPORTED_PROTOCOL_VERSION`, `COMPONENT_NOT_AVAILABLE`, `COMPONENT_LOAD_FAILED`, `RUNTIME_VARIANT_NOT_AVAILABLE`,
  `RUNTIME_INITIALIZATION_FAILED`, `INVALID_INPUT`, `INFERENCE_FAILED`, `OUT_OF_MEMORY`, `SHARED_MEMORY_UNAVAILABLE`,
  `SHARED_MEMORY_INVALID`, `INTERNAL_WORKER_ERROR`. A bad request, a failing handler and a missing handler are all answered; none
  stops the worker.
- **Big data travels in shared memory**, not through the pipe: the backend creates a segment for the pixels; the worker creates
  segments for its results and keeps them until `RELEASE_OUTPUT`. A descriptor is validated (shape fits size) and the attacher
  checks the real segment size before reading.
- **Strict parsing**: exact keys, exact types (a bool is not an int); every rule is checked in the constructor, so a message built
  in process is validated like one off the wire.
- **Models are loaded lazily and verified**: a variant is loaded the first time a request names it; the file is read once, its
  SHA-256 compared with the recorded one, and the session is built **from those bytes** (SEC-007). The provider is exactly the one
  asked for: ONNX Runtime would quietly use the CPU if CUDA failed, so the worker checks and errors instead, and **the worker never
  decides fallback** ([next lessons](03-perception-client-and-providers.md)).
- **Known pipelines only**: the handlers implement two reference contracts (`scrfd-letterbox-v1`, `arcface-112-similarity-v1`). A
  component declaring another contract gets `COMPONENT_NOT_AVAILABLE`, never vectors from the wrong pipeline under the right label.
- **GPU** libraries are machine-local: `FACEIDENTIFY_ORT_GPU_DIR` names the folder the worker activates before importing models
  (`gpu_path.py`); unset changes nothing.
- The worker exits quietly when its parent goes away (a closed connection).

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/contracts/test_ml_ipc_contract.py tests/integration/test_ml_worker_loop.py tests/integration/test_ml_perception_handlers.py -q
```

Expected: `260 passed` (observed). Read
`test_ml_worker_loop.py` names: one per way a request can end. The loop tests drive the worker in-process with fake handlers, so no
model is needed. Real inference is `tests/e2e/test_real_models.py` (local only).

## 5. Change it

A new operation is a protocol change: add it to `MLOperation`, the typed input and output in `messages.py` with its validation,
a handler, the client call, and contract tests (`test_ml_ipc_contract.py` pins the wire shapes). Change the spec
(`API and Contracts.md`) first; the contract tests are the bridge.

## 6. Break it on purpose

Send the loop a request with a field of the wrong type (the contract tests do this): the answer is `ERROR` `INVALID_REQUEST`, and
the worker keeps serving. A worker that dropped such a request would hang the supervisor, which is why "answering is total".

## 7. Exercises

1. Why does the worker have no database?
2. Why is a zero-face image a success?
3. Why are pixels sent through shared memory?
4. Who decides to fall back from CUDA to CPU, and why not the worker?

**Answers**

1. It is a model runner only; keeping it ignorant of the application makes it replaceable and unable to damage the library.
2. An image with no faces is a normal result; an error would look like a fault.
3. Images are large; copying them through a pipe would be slow.
4. The backend: it can record the fallback as provenance and apply policy; the worker would hide it.

## 8. Related files

- Next: [02 The supervisor](02-supervisor.md)
- [`backend/ml/contracts/protocol.py`](../../../../../backend/ml/contracts/protocol.py), [`backend/ml/worker/loop.py`](../../../../../backend/ml/worker/loop.py)
