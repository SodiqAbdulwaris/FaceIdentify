# Readiness names the device in use; why the live library was not moved to DirectML

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** follow-up to the DirectML adapter change (owner decision 2026-11-12:
  show which device is in use)
- **Status:** done (readiness); the live library move **not done**, for the reasons below
- **Commits:** PR (number recorded when merged): `feat(api): show the device in use in readiness`

## What changed

- The worker's `ExecutionProvenance` carries `adapter`: the device a session runs on as the system
  names it (the DirectML adapter's name, or `CPU`), remembered by `load_session` for each session it
  loads (`onnx_session.adapter_of`). Empty when the worker cannot tell; it decides nothing.
- `PerceptionClient` passes it to its `on_ran` observer, and the host's `ClientPool` records it per
  stage. `GET /readiness` reports `execution_device` beside `execution_provider` and
  `provider_fallback` (`NOT_STARTED` before the first request; a stage whose worker named no device
  shows its provider).
- On the development laptop, a real host on a scratch state with the DirectML package processed one
  picture and readiness then read `execution_provider: DmlExecutionProvider`,
  `execution_device: NVIDIA GeForce RTX 4070 Laptop GPU`.

## Moving the owner's live library to the DirectML package: not done

The orchestrating session relayed the owner's authorisation (2026-11-12) to move the live library to
the package with DirectML variants if the gain is not negligible. It is not negligible (3.6 against
10.1 video seconds per second on one episode). What the move would be, per
`INSTALLING_MODELS_WINDOWS.md` and the code on `main` (`493fd2d`):

- **Not a re-registration.** The library stores the manifest it registered under the key
  `insightface-buffalo-l`; registering any other manifest under that key is refused ("a different
  package is registered under this key", `backend/app/runtime/registration.py`), after which
  processing reports the package unavailable.
- **Not a reprocess**, and no decision would change: a representation space's identity is the
  weights digest and the contracts, deliberately **not** the provider, variant or device
  (`registration.py`, owner decision of 2026-10-02). The DirectML package ships the same weights, so
  its vectors are in the same space as the stored ones (measured agreement 2.4e-7 on 2026-10-15) and
  existing faces stay comparable.
- **It needs a package-upgrade path that does not exist yet.** Either a new package key that shares
  the catalog rows (the route the 2026-10-15 entry deferred to M8; it changes `PACKAGE_KEY` for the
  host and the M8 model installer, and needs a policy file under the new key), or registration
  accepting, under the same key, a manifest that keeps every export and only adds variants (an
  in-place upgrade; the catalog's "rows are immutable" rule makes that a spec decision). Both are
  code plus a spec decision, not an operational step.

So the live library still runs on the CPU and nothing in the live state was touched. The policy file
`local-models/state/policies/insightface-buffalo-l.json` and the index
`local-models/state/indexes/f0fd4e92c8c8492097e2307e82000af9` are as they were. **Recommended next
task:** the in-place upgrade (same key, same exports, more variants), which keeps the policy path,
the installer's key and every stored vector, with a test on a copy of a registered library and the
backup-and-restore steps the orchestrator listed before the live state is touched.

## Verification

- `uv run pytest -q tests/contracts/test_ml_ipc_contract.py tests/integration/test_ml_perception_handlers.py
  tests/integration/test_runtime_perception_client.py tests/integration/test_real_profile.py
  tests/integration/test_worker_arbitration.py tests/integration/test_ml_supervisor.py`: 383 passed.
  New: the client hears the worker's device; readiness names a stage's device; a real worker's CPU
  session reports `CPU`; the wire contract carries and checks the field.
- Real host, development laptop: readiness as above.
