# M3: the reference detector and embedder contracts (step 7, first part; TST-038 and TST-039)

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M3 · TST-038, TST-039 (in progress)
- **Status:** partial: the model-independent half. ONNX sessions, the worker handlers, catalog registration and the backend client are the next parts of step 7.
- **Commits:** PR (this branch): `feat(ml): version the SCRFD and ArcFace pre- and postprocessing`

## What changed
`backend/ml/perception/` (worker-side, NumPy and Pillow only; no ONNX Runtime, no weights):
- `detection.py`, contract `scrfd-letterbox-v1`: `letterbox` (longer side scaled to 640 bilinearly, pasted top-left on a zero square, `(pixel - 127.5) / 128`, RGB, channels first, `float32`), `decode` (nine tensors, three per stride 8/16/32, two anchors per cell, distances and landmark offsets in strides; score threshold, greedy NMS, undo the scale, normalise to the image) and `non_maximum_suppression`.
- `alignment.py`, contract `arcface-112-similarity-v1`: the five-point 112 template, a least-squares similarity transform (Umeyama; never a reflection), `align` (Pillow affine resampling, black outside the image), `preprocess` (`(pixel - 127.5) / 127.5`, RGB, channels first) and `canonical_vector` (finite, the model's dimension, L2 norm one, little-endian `float32`).
- Tests: `tests/unit/test_perception_detection.py` and `tests/unit/test_perception_alignment.py` (54 tests, 100% coverage of the package), on synthetic tensors and pictures.

## Why
ML spec 8.1: the detector input transform, coordinate transforms, alignment geometry, pixel normalisation and output normalisation are a contract, and changing any of them is a compatibility change. 18.1: the reference models are replaceable implementations behind model-independent contracts, and the preprocessing and normalisation contract versions are part of a representation space's identity. So the two `VERSION` strings are the values a space will record.

## Decisions (the agent's, inside the owner's reference-model decision; say so if you disagree)
- The numbers (640 input, mean and std, anchor layout, 0.5 score threshold, 0.4 NMS overlap, the template) are the published reference defaults of those two models, recorded as the contract, and provisional like every threshold (ML 18.1).
- A box is **clipped** to the image; a detection with a landmark **outside** the image is **dropped**, not clamped (ML 4.1: out-of-bounds output is rejected before alignment; aligning from a guessed point would be a silent error). Consequence: a face whose eye or mouth corner lies beyond the border is not detected. The alternative (clamp) would align on invented points.
- Malformed model output (wrong tensor count or shape, a value that is not finite, a vector of the wrong length or of zero length) is `INFERENCE_FAILED`; a wrong input is `INVALID_INPUT`. Both are `ContractError`s the worker loop already turns into responses.
- Detection order is best score first and deterministic (stable sort; a tie keeps the earlier box).

## Verification
- `uv run pytest tests/unit/test_perception_*.py --cov=backend.ml.perception`: 54 passed, 100%.
- Mutation pass over 44 mutations of both modules (thresholds, strides, scale, clipping, edges, anchor layout, normalisation, channel order, reflection, shift, fill colour, every guard): the first run left seven survivors (the scale applied to landmarks, the top/bottom clip, a landmark exactly on an edge, a box touching the bottom, a one-pixel-wide image, the score threshold equality); each got a test and the second run left none. One guard no test could observe (`min(size, …)` in the letterbox resize) was deleted.
- Full gate: see the PR.

## Open issues / follow-ups
- The rest of step 7: ONNX Runtime sessions loaded from an installed package (digest re-checked), the two worker handlers, the space identity with `weights_digest`, catalog registration (issue 80), the backend client writing PENDING output.
- Real SCRFD/ArcFace weights are not available here and their licence is unverified (issue 69); the model tests will use small generated ONNX fixtures.
