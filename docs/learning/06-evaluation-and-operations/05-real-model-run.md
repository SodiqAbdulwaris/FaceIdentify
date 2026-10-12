# Evaluation 05 A real-model run

## 1. What this is and why it exists

Everything in the earlier lessons works on a fake model. This lesson is the path to the real one: install the reference model package
(`buffalo_l`: SCRFD to find faces, ArcFace to embed them), prove it runs on pictures, then let the real profile use it. The weights are
research-licensed and never committed; this is a **local** procedure on your machine.

## 2. Where it lives

| Step | Command or file |
|---|---|
| Model files (yours, never committed) | `local-models/buffalo_l/` (git-ignored), for example `det_10g.onnx`, `w600k_r50.onnx` |
| Install as a runtime package | `scripts/install_reference_models.py` |
| Smoke test on pictures | `scripts/smoke_real_models.py` |
| Real-worker pytest (local only) | `tests/e2e/test_real_models.py`, `tests/e2e/test_real_host.py` (`-m e2e`) |
| Package key / policy file | `insightface-buffalo-l`; `<local state>/policies/insightface-buffalo-l.json` |
| Providers | `FACEIDENTIFY_PROVIDERS` (for example `CUDAExecutionProvider,CPUExecutionProvider`); GPU libraries via `FACEIDENTIFY_ORT_GPU_DIR` |

## 3. How it works

1. **Install** (`--models-dir --detector --embedder --local-state-root`; optional `--key --version --dimension`): the script *measures* the
   files (size and SHA-256), builds the manifest and installs it atomically through the same store the app uses
   ([packages and the catalog](../03-backend/runtime-and-worker/04-packages-and-catalog.md)).
2. **Smoke test** (`--local-state-root`; optional `--key --providers --allow-fallback`, then picture paths): builds the plan from the installed package, starts the
   real worker behind the supervisor, detects and embeds every face and prints what it found, how long it took and the cosine similarity of every pair of faces.
   A local developer check, not part of CI.
3. **Policy file**: write the abstain-only policy (or one produced by `measure_operating_point.py --write-policy`) at the path above; the real
   profile accepts only abstain-first policies ([profiles](../03-backend/architecture/04-profiles.md)).
4. **Run the real host**: `python -m backend.api.host` **without** `--development-profile`, on a *new* library (a development library is refused),
   with `FACEIDENTIFY_PROVIDERS` set if you want CUDA. `/readiness` shows `runtime_package` and `processing_policy` `READY`.
5. **Pytest e2e** (local): `uv run pytest -m e2e tests/e2e/test_real_models.py` after installing the models and putting pictures in `local-models/images`
   (named `<person>N.jpg`; same letters means same person).

## 4. Try it

**Needs the local models: describe only; not run here.** Shapes, from the scripts' own docstrings and `--help` (flags verified 2026-10-12):

```bash
uv run python scripts/install_reference_models.py --models-dir local-models/buffalo_l \
    --detector det_10g.onnx --embedder w600k_r50.onnx --local-state-root local-models/state
uv run python scripts/smoke_real_models.py --local-state-root local-models/state \
    --providers CPUExecutionProvider local-models/images/a1.jpg local-models/images/a2.jpg
uv run pytest -m e2e tests/e2e/test_real_models.py
```

**What runs without models (verified 2026-10-12):** the help of both scripts, the profile checks on a real-profile library with no model
(`DEGRADED`, `503 PROCESSING_UNAVAILABLE`, and the policy-file toggle) in [profiles](../03-backend/architecture/04-profiles.md), the
package-store, registration and perception-client tests (`117 passed` and `96 passed`, [runtime](../03-backend/runtime-and-worker/README.md)), and
`FACEIDENTIFY_PROVIDERS` parsing ([perception client](../03-backend/runtime-and-worker/03-perception-client-and-providers.md)).

## 5. Change it

Never commit weights, pictures or reports. A different model is a different package, plus a different worker module if its pre/postprocessing
differs, plus a new measurement before any policy that can match is admitted. Record any new third-party model in
`docs/research/licensing-and-commercialization.md` (a project rule).

## 6. Break it on purpose

Start the real host before installing anything: it is `DEGRADED`, `process` answers `503`, and nothing is invented
([profiles lesson](../03-backend/architecture/04-profiles.md), observed). That honest failure is the design.

## 7. Exercises

1. Which environment variable chooses CUDA first, CPU second?
2. Why must the real host start on a new library?
3. What does the smoke test prove, and what does it not?

**Answers**

1. `FACEIDENTIFY_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider`.
2. A library records its profile; the development and real profiles are never mixed.
3. That the models run through the production client and produce valid vectors; not that the product recognises people, and not calibration.

## 8. Related files

- Previous: [04](04-label-review-tool.md) · Next: [06 Rules, branches and reviews](06-rules-branches-reviews.md)
- [`scripts/install_reference_models.py`](../../../scripts/install_reference_models.py), [`scripts/smoke_real_models.py`](../../../scripts/smoke_real_models.py), [`docs/research/reference-model-selection.md`](../../research/reference-model-selection.md)
