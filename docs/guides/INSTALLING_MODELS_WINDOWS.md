# Installing the face models and the GPU runtime on Windows

How to go from a fresh clone to the real recognition path on a Windows machine: the ONNX Runtime
build, the `buffalo_l` weights, the runtime package, the decision policy, and the check that it all
runs on the GPU. Written 2026-10-16; the facts behind each step are in the linked implementation
entries.

**Licence first.** The `buffalo_l` weights are InsightFace's pretrained models, "available for
non-commercial research purposes only". FaceIdentify uses them as developer-supplied local files for
a personal, local application: an owner-accepted risk, not a verified permission, and a release
blocker ([`reference-model-selection.md`](../research/reference-model-selection.md),
[`licensing-and-commercialization.md`](../research/licensing-and-commercialization.md) section 2).
Never commit, bundle or share the weights; `local-models/` and `*.onnx` are Git-ignored.

## 1. The ONNX Runtime build (DirectML, then the CPU)

```bash
uv sync
uv run python -c "import onnxruntime as o; print(o.__version__, o.get_available_providers())"
```

On Windows `uv sync` installs `onnxruntime-windowsml` 1.30.0 (DirectML and the CPU in one wheel);
the plain `onnxruntime` package is not installed beside it (only one build can be). The check should
print `1.30.0 ['DmlExecutionProvider', 'CPUExecutionProvider']`. DirectML needs a DirectX 12 GPU;
NVIDIA was verified on 2026-10-15, AMD and machines without DirectX 12 are not
([entry](../implementations/2026-10-15-ship-onnxruntime-windowsml.md)). Without a usable GPU the
worker falls back to the CPU and says so (below).

## 2. The weights

Download `buffalo_l.zip` from the official InsightFace release
(`https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip`) into
`local-models/_download/`, check it, and unpack it into `local-models/buffalo_l/`:

```bash
sha256sum local-models/_download/buffalo_l.zip
```

| File | Bytes | SHA-256 |
|---|---|---|
| `buffalo_l.zip` | 288,621,354 | `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` |
| `det_10g.onnx` (SCRFD-10GF, the detector) | 16,923,827 | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` |
| `w600k_r50.onnx` (ArcFace ResNet50, the embedder) | 174,383,860 | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` |

Stop if a hash differs: it is not the selected model, and the evaluation evidence does not apply to
it. (In PowerShell, `Get-FileHash <file> -Algorithm SHA256` gives the same digest.) The pack's other
files (`1k3d68.onnx`, `2d106det.onnx`, `genderage.onnx`) are not used.

## 3. The runtime package

The package is installed into a **local state root**, never into a library:

| Who runs it | Local state root |
|---|---|
| The desktop app (`npm run tauri dev`, or a built shell) | `%LOCALAPPDATA%\io.github.sodiqabdulwaris.faceidentify\state` (the shell's `app_local_data_dir` + `state`) |
| A developer host, gate or script | any folder you pass as `--local-state-root`, conventionally `local-models/state` |

```bash
uv run python scripts/install_reference_models.py --models-dir local-models/buffalo_l \
    --detector det_10g.onnx --embedder w600k_r50.onnx --local-state-root <state root>
```

It measures the files again, writes a manifest with their sizes and hashes (and
`redistributable: false`), and installs it as `runtime/packages/insightface-buffalo-l` under the
state root. The manifest declares a DirectML, a CUDA and a CPU variant of each model.

**A package installed before 2026-10-15 has no DirectML variant** and keeps running on the CPU. Do
not simply reinstall it under a library that already registered it: a library refuses a different
manifest for a package it has registered, and the package then shows as unavailable. Reinstall only
for a fresh library or state root, or after deciding to move the existing library
([note](../implementations/2026-10-15-ship-onnxruntime-windowsml.md)).

## 4. The decision policy

The host reads one file, `<state root>/policies/insightface-buffalo-l.json`, on every request. With
no file, processing is unavailable. The code admits only two kinds of policy
([entry](../implementations/2026-10-15-enable-automatic-acceptance.md)):

- **Abstain-only** (assisted recognition: every face after the first waits for you to confirm it):

  ```json
  {"schema_version": 1, "version": "buffalo-l-abstain-only-v1", "min_detection_score": 0.5, "new_identity_ceiling": -1.0, "match_threshold": 2.0, "margin": 2.0}
  ```

- **The owner-approved automatic-matching point** (`buffalo-l-verified-match-v1`, 0.45 / margin
  0.10, no automatic new identity):

  ```json
  {"schema_version": 1, "version": "buffalo-l-verified-match-v1", "min_detection_score": 0.5, "new_identity_ceiling": -1.0, "match_threshold": 0.45, "margin": 0.1}
  ```

Any other matching values are refused (the readiness check reports the policy as unavailable). Keep
a copy of the abstain-only file beside the live one, so you can go back by copying it over
`insightface-buffalo-l.json`; check the copy really is abstain-only (`"match_threshold": 2.0`).

## 5. Choosing the provider

| Setting | Runs on |
|---|---|
| `FACEIDENTIFY_PROVIDERS` unset (the default on Windows) | DirectML, then the CPU |
| `FACEIDENTIFY_PROVIDERS=CPUExecutionProvider` | the CPU only |
| `FACEIDENTIFY_PROVIDERS=CUDAExecutionProvider,CPUExecutionProvider` **and** `FACEIDENTIFY_ORT_GPU_DIR=<absolute path>/local-models/ort-gpu` | CUDA, then the CPU (**developer only**, never shipped) |

The CUDA path needs a machine-local `onnxruntime-gpu` plus NVIDIA's CUDA 12 and cuDNN 9 libraries in
`local-models/ort-gpu` (installed by hand on 2026-10-07; NVIDIA's licences govern those files, see the
licensing record). Without `FACEIDENTIFY_ORT_GPU_DIR`, asking for CUDA silently ends on the CPU
([research](../research/onnx-runtime-gpu-packaging.md)).

## 6. Checking it runs where you think

```bash
uv run python scripts/smoke_real_models.py --local-state-root <state root> \
    --providers DmlExecutionProvider,CPUExecutionProvider <a few .jpg files>
```

It loads the installed package through the real worker, detects and embeds every face and prints
the timings (on a recent NVIDIA laptop GPU about 0.02 s per picture on DirectML, about 0.5 s on the
CPU). In the running app, `GET /readiness` reports `execution_provider` and
`provider_fallback`: on the GPU they read `DmlExecutionProvider` and `NONE`; `ACTIVE` means a GPU
start failed and the CPU took over (the worker's log says why).

## 7. The desktop app on the real models

A debug shell build starts the **development profile** (fake models) unless told otherwise. To run
the real models from `npm run tauri dev`, set `FACEIDENTIFY_DEVELOPMENT_PROFILE=0` before starting
it; a release build uses the real profile by default. A library made under one profile cannot be
opened under the other (issue #137).
