# M3: the ML worker IPC contract (TST-033)

Date: 2026-10-02. Spec: API and Contracts sections 35 to 50. Plan step 3.

## What was built (`backend/ml/contracts/`, standard library only)
- `protocol.py`: `PROTOCOL_VERSION`, the operations (`DETECT_FACES`, `GENERATE_REPRESENTATIONS` only: the worker has no application-domain operation), statuses, the twelve error codes, worker states, the ten control frame types and `ContractError(code, message)`.
- `wire.py`: strict readers (exact keys, a bool is not an int, finite numbers, non-empty strings).
- `shared_memory.py`: `SharedMemoryDescriptor` (name, size, dtype, shape, strides, layout, readonly), validated on construction and on reading: contiguous row-major only, every dimension at least 1, and the array must fit the segment, so a corrupt descriptor cannot send a reader outside it. `describe()` builds one.
- `messages.py`: `MLRequest` and `MLResponse` with the typed inputs (`DetectFacesInput`, `GenerateRepresentationsInput` with `FaceGeometry`) and outputs (`Detection`, `RepresentationResult`), `ExecutionContext` (correlation ids only) and `ExecutionProvenance` (component version, runtime variant, provider, device).
- `control.py`: `hello`, `frame`, `parse_frame` for HELLO, INITIALIZE, READY, EXECUTE, RESPONSE, RELEASE_OUTPUT, PING, PONG, SHUTDOWN, SHUTDOWN_ACK.

## Decisions made while building (the specs leave them open)
- **Plain dicts on the wire, not pickled classes, and no new dependency.** The project has no pydantic or msgpack; dataclasses plus strict readers do the job and keep the contract testable.
- **The response does not repeat the operation.** The spec's `MLResponse` has no such field; the receiver reads it against the pending request (`MLResponse.from_wire(wire, request)`), which supplies the operation, must have the same `request_id`, and bounds the output: a detection may only refer to an image the request sent, and a representation only to a face it asked about (`check_answers`).
- **The constructors are the gate.** Every rule is checked when an object is built, so a request the backend assembles in process is validated like one read from the wire; `from_wire` reads types and constructs. (The first version validated only in `from_wire`, so the send path checked nothing; the review caught it.)
- **A descriptor is self-consistent, not tied to a segment.** The shape must fit the claimed `size_bytes`; whoever attaches a real segment must check that its actual size covers it (TST-034). `float32` means little-endian (Persistence section 23); the descriptor cannot express another byte order.
- **`execution` is required on SUCCESS and optional on ERROR** (an error before any component is resolved has nothing to report).
- **Boxes and landmarks are normalised (0 to 1), a box must have positive area.** The spec says normalised and leaves the rest to the detector; this is the narrowest reading.
- **An image is uint8 HWC with three channels**, as the spec recommends; any other is `INVALID_INPUT`.
- Worker-created output (the embedding) is a descriptor that must match the stated dimension and dtype; the caller releases it with RELEASE_OUTPUT (ownership: the creator owns the lifetime, section 45; built with the supervisor, TST-034).

## Review
OpenCode (`opencode/big-pickle`, plan agent, disposable worktree; Codex over its limit until 2026-10-03): no blocker. Fixed: an integer too large for a float escaped as `OverflowError`; validation only on the read path; no cross-check of response indices; the descriptor safety wording and a wrong spec citation; `except ValueError` swallowing the better message; `describe()` raising `KeyError`; `WorkerState` untested. Left as noted, not changed: the payload of EXECUTE and RESPONSE frames is not validated by `parse_frame` (stated in its docstring); `readonly` is not enforced; `normalization` is a free string until the space contract names the values (Persistence 6.1).

## Verification
`tests/contracts/test_ml_ipc_contract.py` (131 tests): round trips, about 60 malformed-message cases with their codes, the invariants above. 46 mutations of the guards were checked, all caught; survivors along the way led to a deleted redundant strides check (the equality with the contiguous strides already covers it), a deleted equivalent branch, and new tests (zero-area box, empty image list, a status given as text). Backend coverage stays 100%.
