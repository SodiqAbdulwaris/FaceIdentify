# M3: ONNX Runtime detection and representation in the worker (step 7, second part; TST-038 and TST-039)

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M3 · TST-038, TST-039 (in progress)
- **Status:** partial: the worker side is done and tested through a real worker process. The space identity with `weights_digest`, catalog registration (issue 80) and the backend client that writes PENDING output are the rest of step 7.
- **Commits:** PR (this branch): `feat(ml): run the detector and embedder on ONNX Runtime in the worker`

## What changed
- **Dependencies** (the locked stack already names ONNX Runtime): `onnxruntime` (runtime), `onnx` (dev only, to generate test models), and `numpy` moved from the dev group to the runtime dependencies, because `backend/` has long imported it and ONNX Runtime needs it anyway (the PR 83 reviewer's note on the image decoder). A mypy override treats `onnxruntime` as untyped (it ships no stubs).
- `backend/ml/worker/onnx_session.py`: `load_session(path, sha256, provider)`. The file is read once, hashed, and the session is created from **those bytes**, not from the path again (SEC-007: what is executed is what was verified). The provider is exactly the one asked for: not available is `RUNTIME_VARIANT_NOT_AVAILABLE`; a session whose first provider is not the requested one (ONNX Runtime's quiet CPU fallback) is `RUNTIME_INITIALIZATION_FAILED`; an unreadable, changed or unloadable file is `COMPONENT_LOAD_FAILED`. The worker never falls back by itself; the backend decides.
- `backend/ml/worker/perception_handlers.py`: `parse_config` (strict) and `build_handlers(config_text)`, the worker factory. Handlers for `DETECT_FACES` (letterbox, session, decode, per-image `Detection`s, best first, numbered per image) and `GENERATE_REPRESENTATIONS` (align from the face's landmarks, preprocess, session, canonical vector into a worker-made `float32` segment, `normalization = L2_NORMALIZED`). A face without landmarks is `INVALID_INPUT`. Only the operations the configuration has a variant for are served (so the capabilities list is honest).
- Variants are loaded lazily on the first request that names them and cached. A request names the component version in `component` and, when the component has several variants, the one to run in `options["runtime_variant_id"]`. A variant that cannot run is a coded **error answer** (the worker stays alive), which is what lets the backend pick another variant for the fallback decision; a configuration problem at start would only have killed the worker with no code to act on. A failed load is not cached.
- A model that cannot be what the configuration says is refused when loaded: not exactly one input; a detector without nine outputs; an embedder whose static output length differs from the configured dimension.
- `ProcessWorker(factory_path, config=None)` and `load_handlers(factory_path, config=None)`: the supervising process passes the configuration text as an argument to the child (not through the environment).
- `alignment.NORMALIZATION` is now `L2_NORMALIZED` (the example in Persistence 6.2).
- Test models: `tests/fixtures/onnx_models.py` builds a detector (nine contract-ordered outputs reporting planted faces at fixed anchors, none for an all-black picture) and an embedder (a fixed random projection of a 4 x 4 average of the crop) with the `onnx` package. They honour the real tensor contracts so the worker's whole path runs for real; they are not real weights, and none are committed (issue 69).

## Why
M3 plan step 7 (TST-038/039): real inference through the contracts, with model identity and execution kept apart: the digest is checked on the bytes that run (SEC-007) and the execution provider is reported, never substituted (CUDA to CPU is the backend's decision).

## Decisions (the agent's, inside the owner's decisions; say so if you disagree)
- The worker configuration is a JSON text with `variants: [{component_version_id, kind, runtime_variant_id, model_path, sha256, provider, device, [dimension]}]`, written by the backend from what is installed and registered. This is the interface the backend client and the catalog registration (next parts) will fill; `kind` uses the catalog's `FACE_DETECTOR` and `FACE_REPRESENTATION`.
- Fallback is by variant: the request names the variant; there is no `fallback` field and no worker-side retry.
- The embedder dimension is configuration (it is part of the space identity the backend records), checked against the model when it is static.

## Verification
- `tests/integration/test_ml_perception_handlers.py` (see the count below): configuration parsing and refusal; planted faces found where they are (640 x 480, a 1280 x 960 image scaled by one half, several images with their own indexes, two faces best first); an all-black image is a successful empty result; a unit float32 little-endian vector of the model's dimension; same crop, same vector; different crops, different vectors; a zero-vector model is `INFERENCE_FAILED` and leaves no segment; component and variant selection errors; unavailable provider reported; a session loaded once; nothing loaded at start; a failed load retried; digest, missing file, junk bytes; shape checks; the session made from the hashed bytes; the provider-mismatch branch; and two tests in a **real worker process behind the supervisor** (detect, feed its landmarks into represent, read the vector from the worker's segment, release it; and an unavailable provider is an error answer while the worker still pings).
- Mutation pass: 38 mutations (variant selection, caching, every shape check, provenance order, image index and size, landmark guard, normalisation string, operation selection, every configuration check, the digest, provider and provider-mismatch guards, bytes-not-path, the read error type, the configuration hand-over). Two survivors on the first run (a symbolic output length was never exercised; only a missing file, not an unreadable path, was) got tests; the symbolic case needs a stand-in session because ONNX Runtime infers a static length from the graph. None survive.
- Full gate: see the PR.

## Open issues / follow-ups
- The rest of step 7: the space identity (`weights_digest`, contract versions, dimension) recorded in a `RepresentationSpace`, registration of installed packages in the catalog (issue 80), and the backend client that decodes an image into shared memory, calls these operations and writes PENDING observations and representations.
- CUDA has not been exercised (this machine's ONNX Runtime has only the CPU provider); the mismatch branch is tested with a stand-in session, and a real accelerator run needs hardware (a `hardware` test later).
- Real SCRFD/ArcFace weights: unverified licence (issue 69).
