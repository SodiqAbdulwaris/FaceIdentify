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
- **The response does not repeat the operation.** The spec's `MLResponse` has no such field; the receiver parses with the operation of the pending request of the same `request_id` (`MLResponse.from_wire(wire, operation)`).
- **`execution` is required on SUCCESS and optional on ERROR** (an error before any component is resolved has nothing to report).
- **Boxes and landmarks are normalised (0 to 1), a box must have positive area.** The spec says normalised and leaves the rest to the detector; this is the narrowest reading.
- **An image is uint8 HWC with three channels**, as the spec recommends; any other is `INVALID_INPUT`.
- Worker-created output (the embedding) is a descriptor that must match the stated dimension and dtype; the caller releases it with RELEASE_OUTPUT (ownership: the creator owns the lifetime, section 45; built with the supervisor, TST-034).

## Verification
`tests/contracts/test_ml_ipc_contract.py` (88 tests): round trips, 40-odd malformed-message cases with their codes, the invariants above. 29 mutations of the guards were checked; three survivors led to a deleted redundant strides check (the equality with the contiguous strides already covers it), a deleted equivalent branch, and two new tests (zero-area box, empty image list). Backend coverage stays 100%.
