# Ship ONNX Runtime with DirectML on Windows (Windows ML), CPU fallback

- **Date:** 2026-10-15
- **Milestone / tracker IDs:** M5 track R (R2 follow-up); TST-038 / TST-039 (real path, GPU);
  TST-074 (DirectML validation, partly: this machine only)
- **Status:** done on this machine. AMD GPUs and machines without a DirectX 12 GPU are not verified
  (see *Open issues*)
- **Commits:** PR (number recorded when merged): `build(deps): ship onnxruntime-windowsml on
  Windows`, `fix(runtime): fall back to the CPU when DirectML cannot start`, `feat(runtime): prefer
  DirectML then the CPU on Windows`, `fix(scripts): map DirectML to a GPU device in the model
  probes`, `docs: record the decision to ship ONNX Runtime with DirectML`, `fix(runtime): keep a
  broken model a load failure on an accelerator`, `docs: address the review of the DirectML change`

## What changed

- `pyproject.toml`, `uv.lock`: on Windows the dependency is `onnxruntime-windowsml==1.30.0.*`
  (DirectML and the CPU in one 74 MB wheel); elsewhere `onnxruntime>=1.30.0` (the CPU build, which
  Linux CI keeps). An environment marker chooses; the two cannot be installed together, and
  `uv sync` on Windows installs only `onnxruntime-windowsml` (checked: `uv pip list`).
- `backend/ml/worker/onnx_session.py`: when creating a session for an accelerator raises, the error
  is `RUNTIME_INITIALIZATION_FAILED` (a provider failure: the backend tries the next variant), not
  `COMPONENT_LOAD_FAILED`. Only a failure on the CPU is the model's failure. DirectML sessions are
  created with `enable_mem_pattern = False` and sequential execution, which DirectML requires.
- `backend/api/real.py`: `DmlExecutionProvider` is a known provider. With `FACEIDENTIFY_PROVIDERS`
  unset, `providers_from` gives `DmlExecutionProvider, CPUExecutionProvider` on Windows
  (`WINDOWS_PROVIDERS`) and the CPU alone elsewhere. CUDA runs only when named.
- `backend/app/runtime/reference_package.py`: the reference package declares a DirectML variant per
  model as well as CUDA and CPU (the representation space is unchanged: the provider is not part of
  its identity).
- `scripts/smoke_real_models.py`, `tests/e2e/test_real_models.py`,
  `evaluation/measure_operating_point.py`: map DirectML to a GPU device (they raised `KeyError`).
- Tests: `tests/fixtures/directml_cannot_start.py` (a worker factory where DirectML is listed but
  its session raises, on any operating system);
  `test_directml_that_cannot_start_falls_back_to_the_cpu_visibly` (a real worker behind the real
  `ClientPool`: both stages run on the CPU, the failure is recorded with DirectML's own error, one
  warning per stage, readiness `CPUExecutionProvider` / `ACTIVE`); the start-failure classification
  per provider and the DirectML session options; `providers_from` per platform; the reference
  manifest's three variants.
- Docs: the dated decision note after every passage that stated the losing version
  (`docs/research/tech-stack.md` architecture tree and sections 7, 12 and 20;
  `docs/specs/IMPLEMENTATION_ARCHITECTURE.md` tree, section 13 and the final stack table;
  `docs/specs/ML_COMPONENTS_AND_EVALUATION.md` sections 13 and 18.1;
  `docs/strategy/ML_BENCHMARKS_AND_EVALUATION_PROTOCOL.md` section 13; `docs/plans/Roadmap-Plan.md`
  fallback chain; the licensing record), the research document's *Implementation* section, the
  learning guides that described the default as "CPU only", `.agents/CONTEXT.md` and
  `docs/plans/PROJECT_STATUS.md`.

## Why

The owner's decision of 2026-10-15 (`.agents/CONTEXT.md` Known conflicts 32), in the owner's words:
"Ship onnxruntime-windowsml 1.30.0 on Windows (DirectML for NVIDIA, AMD and Intel, then CPU), keep
onnxruntime on Linux CI through a marker, keep CUDA developer-only, and make a DirectML start
failure fall back to CPU." The measurements and options are in
`docs/research/onnx-runtime-gpu-packaging.md`.

## Decisions

- **The fix is in `load_session`, the one place every variant is loaded**, not in the perception
  client's list of fallback codes: `COMPONENT_LOAD_FAILED` must keep meaning "the model is broken"
  so a genuine model error is never retried away. An accelerator's start failure is a provider
  failure; the CPU variant that runs next would hit a broken model too and report it as
  `COMPONENT_LOAD_FAILED`.
- **A broken model stays a model failure on every provider** (found by the review): ONNX Runtime
  raises its own types for the model itself (`InvalidProtobuf`, `InvalidArgument` for a model that
  fails validation such as one with no graph (found by the re-review), `InvalidGraph`, `NoModel`,
  `NotImplemented`), and those stay `COMPONENT_LOAD_FAILED` even on an accelerator, so a plan with no
  CPU variant still says the model is broken. Checked on the real DirectML build with bytes that are
  not a model: `COMPONENT_LOAD_FAILED ... INVALID_PROTOBUF`.
- **ONNX Runtime falls back by itself.** Its Python `InferenceSession` catches a provider that will
  not start, prints an `EP Error ... Falling back to ['CPUExecutionProvider']` banner on standard
  output and builds a CPU session. The worker's existing check (the session's first provider must be
  the one asked for) already turns that into `RUNTIME_INITIALIZATION_FAILED`; the new branch covers
  the failures ONNX Runtime does not retry. Turning ONNX Runtime's retry off is not possible through
  the constructor, so it was left (the banner goes to the worker's standard output, not to its
  message pipe).
- **Pin `==1.30.0.*`, not `==1.30.0`.** The wheel's version is `1.30.0.202609102321`; the exact pin
  matches nothing.
- **CUDA keeps its variant** in the reference package so the developer path
  (`FACEIDENTIFY_ORT_GPU_DIR`) still works when `FACEIDENTIFY_PROVIDERS` names it; it is never a
  default and never shipped.
- **`real_processing`'s own default stays the CPU**: every caller goes through `providers_from`,
  which applies the platform default.
- **Not added:** a choice of DirectML adapter (`device_id`): DirectML's default adapter was the RTX
  here (the model alone ran in 0.006 s); a machine whose default is a weak integrated GPU would still
  run, slower. Add it if a measured machine needs it.

## Verification

- `uv sync` on Windows: only `onnxruntime-windowsml 1.30.0.202609102321` installed (no plain
  `onnxruntime`); `onnxruntime.get_available_providers()` is
  `['DmlExecutionProvider', 'CPUExecutionProvider']`, version `1.30.0`; `providers_from({})` on
  this machine is `('DmlExecutionProvider', 'CPUExecutionProvider')`.
- New tests fail without the `load_session` change (checked by restoring the old file:
  `test_directml_that_cannot_start_falls_back_to_the_cpu_visibly` and the DirectML options test
  failed) and pass with it.
- On this machine (RTX 4070 Laptop + Intel UHD), a probe through the real worker with the package
  re-made from the new manifest in a scratch local state root (`local-models/state` was not touched:
  another session's CelebA gate was using it), first 30 LFW `*_0001.jpg` pictures. **The CPU was
  heavily contended by that gate**, so the timings are not comparable with PR 200's:

  | Provider | First picture | Steady detect, median / p90 | Steady embed, median / p90 |
  |---|---|---|---|
  | DirectML | 2.6 s + 1.9 s | 0.122 / 0.195 s | 0.044 / 0.066 s |
  | CPU | 1.5 s + 0.8 s | 0.170 / 0.695 s | 0.671 / 1.460 s |

  (A second run: DirectML 0.133 / 0.055 s, CPU 0.190 / 0.797 s median.) The detector alone on
  DirectML's default adapter took 0.006 s (median of 20, 640 × 640), so the per-picture time is CPU
  work in the worker starved by the gate. DirectML and CPU embeddings of the same 30 faces agree to
  1 − cos ≤ 2.4e-7.
- Forced start failure on the real build: the real worker with DirectML asked for adapter 99
  (`887A0002 ... no adapter with the specified ordinal`, a genuine DirectML error) ran both stages
  on the CPU; each DirectML variant was recorded as `RUNTIME_INITIALIZATION_FAILED`; one warning per
  stage; readiness `execution_provider` `CPUExecutionProvider`, `provider_fallback` `ACTIVE`.
- Full gate: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy
  --platform linux && uv run pytest -q` (result recorded in the PR description). No full evaluation
  gate was run (not asked).

## Review

Codex CLI (`codex exec -s read-only`, disposable worktree, clean afterwards) reviewed the first five
commits and asked for changes: (high) installed packages and registered libraries have no upgrade
path to the new manifest; (medium) a broken model on an accelerator became a provider failure;
(low) the decision notes put the source inside the bold date, one note split the licensing table,
the benchmark protocol's section 2 still said "CUDA is primary" without a note, and the status page
said "the installer ships" although no installer exists. The medium and low findings are fixed. The
high one is answered on the PR and kept below as a follow-up. The answer rests on an
**assumption, not confirmed with the owner**: that no long-lived library uses the real profile
today. A debug desktop build starts the development profile by default, but a release build uses
the real profile, and `FACEIDENTIFY_DEVELOPMENT_PROFILE=0` turns it on in a debug build
(`desktop/src-tauri/src/config.rs`); evaluation gates and the real-host e2e test make fresh
libraries. A new package key would also orphan the measured policy file
(`policies/<package key>.json`), so the upgrade path belongs with M8's package management. A
Codex re-review of the fixes found a second model error (`InvalidArgument`, a model with no graph)
and this overstatement; both are fixed.

## Open issues / follow-ups

- **Not verified:** an AMD GPU; a machine with no DirectX 12 GPU (the forced failure was a missing
  adapter on a machine that has two); Windows ML on the Intel UHD (the Intel figure is from
  `onnxruntime-directml` 1.23.0); uncontended timings.
- **A DirectML failure during inference** (device removed, out of memory) is the operation's error,
  not a fallback: only start failures fall back. Revisit if it is seen.
- **The installed package must be reinstalled to gain the DirectML variants.** A package installed
  before this change declares CUDA and CPU only: with the new default it runs on the CPU (readiness
  `CPUExecutionProvider`, fallback `NONE`, because the plan has no DirectML variant to fall back
  from). The package store refuses a different manifest under the same key, so reinstalling means
  removing `<local state>/runtime/packages/insightface-buffalo-l` and running
  `scripts/install_reference_models.py` again; and a library that registered the old manifest
  refuses the new one ("a different package is registered under this key"), so its processing would
  report the runtime package unavailable. Evaluation gates make fresh libraries, so they are not
  affected; any long-lived library would be. **An upgrade path for a changed package manifest**
  (a new key or version that shares the catalog rows, with the policy file following it) is needed
  before the real profile serves a library that must survive a package change (M8).
- **Telemetry:** `onnxruntime-windowsml`'s `Privacy.md` says official builds send trace events
  through Windows' ETW telemetry by default, subject to the user's Windows diagnostic-data setting
  (the CPU wheel's official Windows build is the same). Whether the worker should call
  `onnxruntime.disable_telemetry_events()` is a privacy decision for the owner.
- **The operating point** was measured on the CPU; re-measure on DirectML before relying on it
  (embeddings agree to 2.4e-7 here, so no change is expected). **Done 2026-10-16:** identical
  decisions and metrics ([entry](2026-10-16-directml-remeasure.md)).
- The `DirectML.dll` terms were read from the `Microsoft.AI.DirectML` 1.15.4 NuGet package; the
  wheel does not carry them, so that they govern the wheel's copy is an inference.
