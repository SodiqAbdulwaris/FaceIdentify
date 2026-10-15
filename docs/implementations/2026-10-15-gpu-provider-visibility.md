# The GPU on this machine, a visible CPU fallback, and which ONNX Runtime build to ship

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R (R2 follow-up); TST-038 / TST-039 (real path, GPU)
- **Status:** partial: the fallback is visible and the GPU path is verified on this machine; **the
  shipped build is the owner's decision** (`.agents/CONTEXT.md`, Known conflicts, item 32)
- **Commits:** PR #200 (to be recorded when merged): `feat(runtime): report the execution provider
  and fallback in readiness`, `docs: compare ONNX Runtime GPU builds and record the decision owed`,
  `fix(runtime): notify the provider observer after releasing output`, `docs: qualify the DirectML
  fallback claim after review`, `test(runtime): type the scripted worker as a supervisor for mypy`,
  `docs: record the re-review of the GPU provider change`

> **Decision 2026-10-15:** (owner; `.agents/CONTEXT.md` Known conflicts 32) the shipped build is decided: "Ship onnxruntime-windowsml 1.30.0 on Windows (DirectML for NVIDIA, AMD and Intel, then CPU), keep onnxruntime on Linux CI through a marker, keep CUDA developer-only, and make a DirectML start failure fall back to CPU." Implemented in [`2026-10-15-ship-onnxruntime-windowsml.md`](2026-10-15-ship-onnxruntime-windowsml.md).

## What changed

- `backend/app/runtime/perception_client.py`: an optional `on_ran` callback hears the variant that
  actually ran after every successful `detect` and `represent` (never after a refused provider or a
  failure), called once the call has released what it holds.
- `backend/api/real.py`: `ClientPool` passes that callback to every client. It remembers, per
  stage, the provider that last ran and whether that was the stage's preferred one. It logs a change
  (`faceidentify.runtime`; a fallback is a WARNING naming the preferred provider, once per change,
  not once per job). It reports two readiness capabilities: `execution_provider` (the provider(s)
  that last ran, `NOT_STARTED` before any job) and `provider_fallback` (`ACTIVE` while any stage
  runs on a fallback, otherwise `NONE`).
- `evaluation/assisted_recognition_gate.py`: the report records `readiness_after_enrolment`, so an
  evaluation says which provider it ran on, not only which ones it asked for.
- `docs/research/onnx-runtime-gpu-packaging.md`: the measured comparison of ONNX Runtime builds and
  the recommendation.

Nothing changed in what is installed: the project still depends on the CPU `onnxruntime` 1.30.0;
the CUDA path is still the machine-local `local-models/ort-gpu` named by `FACEIDENTIFY_ORT_GPU_DIR`.

## Why

The owner (2026-10-15) wants the GPU used on this machine, and a later installer that is easy to
install and runs on CPU-only and non-NVIDIA machines. The GPU sat at 0% because the project
environment has the CPU build, and a run that asked for `CUDAExecutionProvider,CPUExecutionProvider`
without `FACEIDENTIFY_ORT_GPU_DIR` fell back to the CPU on every job without saying so (reproduced
below). Spec: ML §13 (FastAPI "records explicit fallback"); the brief asked for a fallback that is
"logged, reported in readiness".

## Decisions

- **Visible, not louder:** a fallback still runs the job (that is the planned fallback, ML §13); it
  is now logged and shown in readiness. The durable record stays in the run's execution segments.
- **Log on change only:** a 1,000-picture run on a machine without CUDA logs two warnings (one per
  stage), not 2,000.
- **Not changed without the owner:** the default providers (`FACEIDENTIFY_PROVIDERS` unset still
  means the CPU alone), the dependency, the reference package's variants and anything an end user
  installs. The recommendation (ship `onnxruntime-windowsml`, DirectML first and the CPU second, on
  Windows; keep CUDA as a developer-only option) is in the research note and is asked as item 32.

## Verification (this machine, 2026-10-15)

An evaluation gate run (another session) was using the CPU throughout, so CPU timings are inflated.

- Providers: `uv run python -c "import onnxruntime as o; print(o.get_available_providers())"`:
  `['AzureExecutionProvider', 'CPUExecutionProvider']` (1.30.0). With `FACEIDENTIFY_ORT_GPU_DIR`
  set, the worker imports `onnxruntime-gpu` 1.23.2, which offers CUDA.
- Timing probe (a scratch script with an `if __name__ == "__main__":` guard, through the real
  worker, supervisor and `PerceptionClient`; `buffalo_l`; the first 30 LFW `*_0001.jpg` pictures;
  medians after the first picture):

  | Provider | First picture | Detect median / p90 | Embed median / p90 |
  |---|---|---|---|
  | CPU (contended) | 2.54 s + 1.54 s | 0.479 / 0.565 s | 0.495 / 0.866 s |
  | CUDA (`onnxruntime-gpu`) | 4.47 s + 0.88 s | 0.025 / 0.032 s | 0.007 / 0.013 s |
  | DirectML (`onnxruntime-directml` 1.23.0, scratch install) | 3.35 s + 0.81 s | 0.023 / 0.027 s | 0.008 / 0.014 s |
  | DirectML (`onnxruntime-windowsml` 1.30.0, scratch install) | 2.67 s + 0.63 s | 0.019 / 0.020 s | 0.007 / 0.014 s |

  So the GPU is about 20 times faster than the uncontended CPU (0.36 s + 0.35 s) per picture.
- Agreement with the CPU (the same 30 pictures, most confident face): CUDA min cosine 0.999986
  (1 − cos ≤ 1.4e-5); DirectML (both builds) 1 − cos ≤ 2.4e-7. DirectML on the Intel UHD
  (explicit `device_id`, model only) matched the CPU to float32 rounding.
- Fallback, worker level: `CUDAExecutionProvider,CPUExecutionProvider` without the GPU folder ran on
  the CPU with the recorded reason "CUDAExecutionProvider is not available on this machine".
- Fallback, application level: `uv run pytest -m e2e tests/e2e/test_real_host.py` (local only)
  with `FACEIDENTIFY_ORT_GPU_DIR` set and CUDA first: 1 passed (readiness `execution_provider` is
  `CUDAExecutionProvider`, `provider_fallback` `NONE`); on the CPU alone: 1 passed; CUDA first
  without the GPU folder: the jobs completed on the CPU, two warnings were logged
  (`FACE_DETECTOR is running on CPUExecutionProvider: the preferred CUDAExecutionProvider is not
  available`, the same for `FACE_REPRESENTATION`), and the test's new readiness assertion failed
  as intended (`'CPUExecutionProvider' == 'CUDAExecutionProvider'`).
- Tests: `tests/integration/test_real_profile.py` (the pool reports the provider, warns once per
  stage, and clears the fallback when the preferred provider is back; readiness starts at
  `NOT_STARTED`/`NONE`) and `tests/integration/test_runtime_perception_client.py` (`on_ran` hears
  the variant that ran, not the refused one, and nothing on a failure): 81 passed.
- Independent review (Codex CLI, read-only, disposable worktree; posted on the PR): no high
  findings; five addressed. (1) An `on_ran` that raised could leave the embedding output
  allocated: the hook now runs after the release, and a regression test fails without the fix
  and passes with it. (2) The research note claimed the fallback "makes every case work": now
  stated as intended and unverified, with the `COMPONENT_LOAD_FAILED` gap named. (3) CONTEXT
  credited Windows ML with the Intel run: corrected (it was `onnxruntime-directml`). (4) The pool
  test called the hook directly: it now drives `detect` and `represent` through a scripted worker,
  and a single-variant stage is covered. (5) The tech-stack reference is section 7, and the NVIDIA
  change from section 7 and 12 is now part of the owner's question.
- Re-review (Codex CLI, same isolation): the five fixes confirmed correct; one new finding, the
  rewritten pool tests handed `ClientPool` a test double mypy refuses (four errors, also caught by
  the full gate). Fixed with a `cast(MLSupervisor, ...)` as in the perception-client tests.
- Gate: see the PR description for the full gate result on the final head.

## Open issues / follow-ups

- **Owner decision (Known conflicts 32):** which ONNX Runtime build the application ships.
- If D is chosen: the dependency swap with an environment marker, `DmlExecutionProvider` in
  `KNOWN_PROVIDERS` and the reference package's variants, DirectML session options in
  `load_session`, classifying a DirectML start failure as `RUNTIME_INITIALIZATION_FAILED` (today an
  exception from `InferenceSession` is `COMPONENT_LOAD_FAILED`, which does not fall back), a
  reinstall of the runtime package, a licensing row for `DirectML.dll`, a fallback test on a
  machine or VM without a DirectX 12 GPU, `tech-stack.md` sections 7 and 12 amended for NVIDIA, and
  the operating point re-measured on DirectML.
- DirectML refused a batch of four faces in ArcFace (`BatchNormalization`); the worker embeds one
  face per call, so the application is unaffected, but batching would need validation.
- To use the GPU here today: set `FACEIDENTIFY_ORT_GPU_DIR` to the absolute path of
  `local-models/ort-gpu` and `FACEIDENTIFY_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider`
  before starting the host or a gate, then check readiness for `provider_fallback: NONE`.
