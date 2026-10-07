# M5 R1: select, verify and install the reference models (issue #69, part 1)

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, R1 and the first part of R2; TST-038, TST-039 (real path, CPU)
- **Status:** partial: selection, packaging, installation and CPU inference are done; CUDA, catalog registration through the real host and the real processing wiring are not
- **Commits:** PR to be recorded when merged

## What changed

- The weights were chosen and recorded: [`docs/research/reference-model-selection.md`](../research/reference-model-selection.md)
  (`buffalo_l`: SCRFD-10GF `det_10g.onnx` and ArcFace ResNet50 `w600k_r50.onnx`; licences, official
  sources, sizes and SHA-256s of the candidates `buffalo_l`, `buffalo_sc` and `antelopev2`).
- `backend/app/runtime/reference_package.py`: builds a runtime-package manifest from two ONNX files
  (measured size and hash, a CUDA then a CPU variant per model, mandatory provenance with
  `redistributable: false`) and lays the package out.
- `scripts/install_reference_models.py`: installs it through the production `RuntimePackageStore`.
- `scripts/smoke_real_models.py`: runs the installed models through the production
  `PerceptionClient`, supervisor and real worker process on real pictures (a local developer check).
- `.gitignore`: `local-models/` (weights, pictures, scratch installs) is never committed.

## Why

M5 plan track R1/R2; issue #69 asks for exact models, sources, hashes, licences and a real
detection, alignment and embedding run. The existing contracts (`scrfd-letterbox-v1`,
`arcface-112-similarity-v1`) were written against these models' published behaviour and had never
met the real weights.

## Decisions

> **Decision 2026-10-07:** The owner delegated the final selection ("select by documented criteria"),
> chose personal/local-only use, and pre-approved downloading official candidates. The agent selected
> `buffalo_l`. The licence ("non-commercial research purposes only") is acceptable for that use and is
> a release blocker.

## Verification

- `uv run pytest tests/unit/test_reference_package.py`: 2 passed, 100% line and branch coverage of the
  builder; five mutations (size, hash, variant order, redistributable flag, dimension) each made them fail.
- Real run (CPU, this machine, four public-domain NASA photographs from Wikimedia Commons, local only):
  faces found with scores 0.76 to 0.90, unit 512-d vectors, same person 0.59 to 0.69, different people
  0.03 to 0.21. The existing detector decode and alignment contracts accepted the real models
  unchanged: the output order and shapes (`[N,1]`, `[N,4]`, `[N,10]` per stride) match. Smoke only,
  not calibration.
- Full gate: see the PR.

## Open issues / follow-ups

- CUDA on the RTX 4070 and CPU/CUDA agreement (next PR); the worker needs the GPU runtime libraries on
  its path.
- Registering the installed package in the library catalog and wiring the real host (client reuse,
  request builder) wait for the calibrated policy shape (R4).
- The licence is a release blocker, not a development one.
