# ONNX Runtime on the GPU: which build to ship

- **Date:** 2026-10-15
- **Status:** measured on the owner's machine; **the recommendation needs the owner's decision**
  (it changes a locked dependency and what end users install; `.agents/CONTEXT.md`, Known
  conflicts, item 32)
- **Implementation entry:** [`2026-10-15-gpu-provider-visibility.md`](../implementations/2026-10-15-gpu-provider-visibility.md)

## The question

The owner wants the GPU used for speed on this machine (RTX 4070 Laptop, driver 576.83, plus an
Intel UHD integrated GPU), and the application shipped later as an installer that is easy to install
and runs on CPU-only machines and on machines without an NVIDIA GPU (AMD, Intel). ONNX Runtime (ORT)
is locked; `tech-stack.md` section 6 already names the direction: CUDA for NVIDIA, DirectML for other
Windows GPUs, the CPU as the universal fallback. Which ORT *build* the application ships is still open.

Only one ORT build can be installed at a time: `onnxruntime`, `onnxruntime-gpu`,
`onnxruntime-directml` and `onnxruntime-windowsml` all provide the same `onnxruntime` module and
overwrite each other. Every build includes the CPU execution provider.

## Why the GPU sat at 0%

The project environment has the CPU build (`onnxruntime` 1.30.0: `AzureExecutionProvider`,
`CPUExecutionProvider`). The CUDA path built on 2026-10-07 (M5 R2) is a machine-local
`onnxruntime-gpu` in `local-models/ort-gpu`, which the worker activates only when
`FACEIDENTIFY_ORT_GPU_DIR` names it. A run that asks for `CUDAExecutionProvider,CPUExecutionProvider`
without that variable falls back to the CPU on every job. The fallback was recorded in each run's
execution segments, but nothing logged it and readiness did not show it. Reproduced 2026-10-15
(probe below: "CUDAExecutionProvider is not available on this machine", ran on the CPU). This
change makes it visible (implementation entry).

## Measurements (2026-10-15, this machine)

Through the production path: the real worker process behind the supervisor and the
`PerceptionClient`, `buffalo_l` (SCRFD `det_10g` + ArcFace `w600k_r50`), the first 30 LFW
`*_0001.jpg` pictures, one worker per run. "Steady" excludes the first picture (session start-up).
**The CPU figures are inflated:** an evaluation gate run was using the CPU at the same time (the
supervisor's earlier uncontended figure is about 0.36 s detect + 0.35 s embed).

| Build, provider | Installed size | First picture (start-up) | Steady detect, median / p90 | Steady embed, median / p90 | Vectors against the CPU (30 faces) |
|---|---|---|---|---|---|
| `onnxruntime` 1.30.0, CPU (contended) | 41 MB | 2.5 s + 1.5 s | 0.479 / 0.565 s | 0.495 / 0.866 s | (reference) |
| `onnxruntime-gpu` 1.23.2 + CUDA 12.9 / cuDNN 9.27 pip wheels, CUDA | 389 MB + 2.5 GB NVIDIA libraries | 4.5 s + 0.9 s | 0.025 / 0.032 s | 0.007 / 0.013 s | 1 − cos ≤ 1.4e-5 |
| `onnxruntime-directml` 1.23.0, DirectML (default adapter: the RTX) | 68 MB | 3.4 s + 0.8 s | 0.023 / 0.027 s | 0.008 / 0.014 s | 1 − cos ≤ 2.4e-7 |
| `onnxruntime-windowsml` 1.30.0, DirectML (default adapter: the RTX) | 74 MB | 2.7 s + 0.6 s | 0.019 / 0.020 s | 0.007 / 0.014 s | 1 − cos ≤ 2.4e-7 |

The model alone with `onnxruntime-directml` (`DmlExecutionProvider` with an explicit `device_id`,
random input, median of 20 calls): **Intel UHD** (adapter 0) 0.067 s detect, 0.055 s embed; RTX
(adapter 1) 0.007 s, 0.006 s; contended CPU 0.44 s, 2.06 s. The Intel output matched the CPU to
float32 rounding (1 − cos < 6e-8, four inputs). Without a `device_id`, the worker's default
adapter was the RTX (its load rose during the run). On the Intel GPU, DirectML is about 7× faster
than this contended CPU for detection.

Not measured: an AMD GPU, a machine with no DirectX 12 GPU, a CPU-only machine with a GPU build
installed. Windows ML's downloadable vendor execution providers were not tested either. One failure
was seen: ArcFace with a **batch of four** faces failed on DirectML (`BatchNormalization`, "The
parameter is incorrect"). One face per call works, and that is what the worker does
(`perception_handlers.py` embeds face by face), so the application is not affected, but batching
on DirectML would need its own validation.

## The options

| | A. CPU build only (today) | B. `onnxruntime-gpu` + NVIDIA pip wheels | C. CPU default + optional NVIDIA pack | **D. `onnxruntime-windowsml` (DirectML) on Windows** |
|---|---|---|---|---|
| GPU on this machine | no | CUDA | CUDA, if the pack is installed | DirectML on the RTX (as fast as CUDA here) |
| AMD / Intel GPUs | no | no | no | yes (any DirectX 12 GPU; Windows 10 1903 or later per Microsoft, not checked here); not tested on AMD |
| CPU-only machine | yes | yes in principle (the CPU provider is inside; CUDA fails to start, then the planned CPU fallback), still ships 2.9 GB | yes | yes (CPU provider inside); a machine with no DX12 adapter should fail DirectML at session start and fall back; not tested |
| Install size | ~41 MB | ~2.9 GB | 41 MB, plus 2.9 GB for NVIDIA users | ~74 MB |
| One wheel covers every case | yes, CPU only | no (2.9 GB for everyone, NVIDIA only) | two installs | **yes on Windows** |
| ORT version | 1.30.0 | 1.23.2 here (1.31.0 exists; it needs CUDA 12/13 matching the driver) | 1.30.0 + 1.2x | **1.30.0, the locked version** (`onnxruntime-directml` stopped at 1.24.4) |
| Licence | MIT | ORT MIT; NVIDIA CUDA/cuDNN proprietary, redistribution terms per file **not verified** | as B for the pack | MIT (wheel `LICENSE`); `DirectML.dll` is Microsoft's, its redistribution terms **not verified** |
| Non-technical user | nothing to do | a 2.9 GB download; the driver must support the CUDA version | a second, technical step | nothing to do |
| Linux CI | unchanged | unchanged | unchanged | needs an environment marker: `onnxruntime-windowsml` on Windows, `onnxruntime` elsewhere |

Notes on B: `onnxruntime.preload_dlls()` (ORT ≥ 1.21) loads CUDA/cuDNN from the `nvidia-*` pip
wheels. The worker already does the same thing by hand (`backend/ml/worker/gpu_path.py` puts every
`nvidia/*/bin` on the DLL search path), so it would add nothing here. The CUDA 12.9 libraries need a
driver that supports CUDA 12.9 (this machine: 576.83); an older driver fails at session start, and then the planned CPU fallback applies.

Notes on D: Microsoft has announced DirectML as in sustained engineering and points new work to
Windows ML (from Microsoft's announcements, not re-checked for this note),
which ships ORT with DirectML and can add vendor providers (NVIDIA TensorRT-RTX, AMD, Intel
OpenVINO) through its execution-provider catalogue. The `onnxruntime-windowsml` wheel used here
exposes `DmlExecutionProvider` and `CPUExecutionProvider`; the catalogue was not tried. It prints
one harmless start-up warning ("Init provider bridge failed": no shared-library provider to load).
DirectML wants `enable_mem_pattern = False` and sequential execution. The worker does not set them
and the run was correct, but a production change would set them explicitly for that provider.

## Recommendation

**D: ship `onnxruntime-windowsml` as the application's ORT on Windows** (keep `onnxruntime` for
Linux CI through an environment marker), with variants ordered DirectML first and the CPU second.
The backend's existing fallback then makes every case work from one install: any DirectX 12 GPU
(NVIDIA, AMD, Intel) runs DirectML, and anything else gets the CPU, logged and shown in readiness.
It is 74 MB rather than 2.9 GB, it is the locked ORT version (1.30.0), it needs no NVIDIA licence
review, and on this machine it matched CUDA's speed and agreed with the CPU more closely than CUDA
does. It is also the direction `tech-stack.md` section 6 already locks ("supported Windows GPU →
DirectML").

**Keep CUDA as a developer-only option**, as it is today (`local-models/ort-gpu` +
`FACEIDENTIFY_ORT_GPU_DIR`): useful for comparison, never shipped. Revisit an NVIDIA pack (option
C) only if a measured workload shows DirectML too slow on NVIDIA. That would also be the trigger
for the TensorRT row in `tech-stack.md`.

What adopting D needs (owner decision first): the dependency swap with its marker and lock file
change; `DmlExecutionProvider` in `KNOWN_PROVIDERS` and in the reference package's variants
(`backend/app/runtime/reference_package.py` declares CUDA and CPU today); the DirectML session
options in `load_session`; reinstalling the runtime package so its catalogue gains the DirectML
variants (the representation space is unchanged, since the provider is not part of its identity);
a licensing row; a test of the fallback on a machine or VM without a DX12 GPU; and re-running the
operating-point measurement on DirectML before relying on it.
