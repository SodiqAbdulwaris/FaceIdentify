# M5 R2: the CUDA runtime on the RTX 4070

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, R2; TST-038, TST-039 (real path, GPU)
- **Status:** done: CUDA runs the real models and agrees with the CPU; the application host uses it only once the real host wiring and a provider choice exist (next changes)
- **Commits:** PR to be recorded when merged

## What changed

- `backend/ml/worker/gpu_path.py`: when the environment variable `FACEIDENTIFY_ORT_GPU_DIR` names a
  directory, the worker (a spawned process, so it does this itself, before any model library is
  imported) puts it first on `sys.path`, so its `onnxruntime-gpu` shadows the CPU build, and
  registers every `nvidia/*/bin` in it on the DLL search path and `PATH`. With the variable unset
  nothing changes. Called from `worker_entry`; `tests/unit/test_gpu_path.py` (3) covers it.
- Nothing else in the application changed: the worker still never falls back by itself
  (`load_session`), so a machine where CUDA cannot start gets a provider error the backend turns into
  the planned CPU fallback.

## The machine-local install (never committed; `local-models/` is Git-ignored)

```bash
uv pip install --python .venv/Scripts/python.exe --target local-models/ort-gpu "onnxruntime-gpu==1.23.2" \
  nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 \
  nvidia-curand-cu12 nvidia-cuda-nvrtc-cu12 nvidia-nvjitlink-cu12
```

installed `onnxruntime-gpu` 1.23.2 with CUDA 12.9 libraries (cuBLAS 12.9.2.10, cuDNN 9.27.0.42,
cuFFT 11.4.1.4, nvJitLink 12.9.86, runtime 12.9.79, NVRTC 12.9.86). The driver (576.83) supports CUDA
12.9; CUDA 13 builds would not work. `--target` also installs the dependencies; delete everything
except `onnxruntime`, `onnxruntime_gpu-*.dist-info` and `nvidia*` from the directory, so the project
environment's own numpy and friends are not shadowed. Set `FACEIDENTIFY_ORT_GPU_DIR` to the absolute
path of `local-models/ort-gpu` before starting the worker or a script that starts one.

## Verification (on this machine, `buffalo_l`, four NASA photographs)

- `scripts/smoke_real_models.py --providers CUDAExecutionProvider`: every stage ran on
  `CUDAExecutionProvider` (the script asserts the provider that executed, and the worker refuses a
  silent fallback).
- Timing, steady state after the first call: detect 0.03 s and embed 0.01 to 0.02 s on CUDA, against
  0.22 to 0.38 s and 0.25 to 0.64 s on the CPU. The first CUDA call took about 5 s (provider
  start-up and kernel load), once per worker.
- CPU against CUDA for the same faces (one worker each): cosine 0.999976, 0.99999, 0.999992,
  0.999979 and 0.999948 for the five faces; worst 0.99995, above the 0.999 bar. The pairwise scores
  of the smoke test agree to 0.001.
- `uv run pytest -m e2e tests/e2e/test_real_models.py` with `FACEIDENTIFY_PROVIDER=CUDAExecutionProvider`:
  1 passed.
- Static gate on both platforms; see the PR for the full-suite result.

## Licences

Every file named above gets its row in `docs/research/licensing-and-commercialization.md` (section 4):
`onnxruntime-gpu` is MIT; the NVIDIA libraries are proprietary and their redistribution terms are
still not verified; they are never committed or bundled, and a release needs the checklist item
there.

## Open issues / follow-ups

- Choosing CUDA first with the CPU as the planned fallback is a request-level setting
  (`runtime_policy.providers`, `allow_fallback`); the real host (next change) takes it from its
  settings, CPU by default.
- Re-measure the operating point on CUDA before relying on it: vectors differ in the fifth decimal,
  which should not move it, but the report records the provider it ran on.
