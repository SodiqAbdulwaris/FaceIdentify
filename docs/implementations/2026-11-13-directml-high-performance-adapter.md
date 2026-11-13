# DirectML on the high-performance GPU, then any adapter, then the CPU

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M6 (video throughput follow-up to the D8 check); owner requirement below
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(ml): run DirectML on the high-performance
  GPU, then any adapter`

> **Owner decision 2026-11-12** (relayed by the orchestrating session in close paraphrase): on any
> user's machine the app checks whether there is a GPU that supports it; if so it uses the GPU, and
> with only a CPU everything runs on the CPU. The adapter choice must be general, not tuned to one
> laptop: prefer the high-performance DirectX 12 adapter, fall back to another adapter and then to the
> CPU when a provider cannot start, with no manual step, and show which device is in use.

## What changed

`load_session` (`backend/ml/worker/onnx_session.py`) creates a DirectML session in this order:

1. `performance_preference=high_performance`, `device_filter=gpu`: the GPU DXGI ranks first for
   performance (the discrete one on a laptop that also has an integrated GPU);
2. no adapter options: the adapter DirectML picks itself;
3. otherwise the provider has failed (`RUNTIME_INITIALIZATION_FAILED`), and the backend falls back to
   the CPU variant as before.

A session that ONNX Runtime quietly moved to the CPU counts as one that did not start, as before.
`FACEIDENTIFY_DIRECTML_ADAPTER` overrides the first choice (`default`, or an adapter number); any
other value fails the provider with a message naming the variable. The adapter in use is written to
the worker's standard error as `ml-worker: DirectML runs on <name as Windows names it>` (from
`ort.get_ep_devices()`), which the host log keeps. Showing it in `/readiness` beside
`execution_provider` would need a field through the worker protocol and the supervisor, which other
work is changing now; that is left as a follow-up.

## Measured (2026-11-13, RTX 4070 Laptop GPU and Intel UHD Graphics, i9-14900HX, idle machine)

Per call, after five warm-up calls, same random inputs; "RTX busy" from `nvidia-smi` while running.

| Session | Detect (640 x 640) | Embed (112 x 112) | RTX busy |
|---|---|---|---|
| CPU | 35.4 to 36.2 ms | 50.3 to 51.3 ms | 0% |
| DirectML, no options (before) | 5.8 to 6.0 ms | 4.4 to 4.5 ms | yes (max 60%) |
| DirectML `device_id=0` | 65.2 ms | 50.2 to 50.3 ms | 0% (the integrated GPU) |
| DirectML `device_id=1` | 6.7 to 7.0 ms | 4.5 to 4.6 ms | yes |
| DirectML high performance, GPU (now) | 5.9 ms | 4.5 to 4.6 ms | yes |
| DirectML minimum power, GPU | 65.2 to 65.3 ms | 50.3 ms | 0% |

**On this laptop, DirectML with no options already ran on the RTX 4070**: adapter 0 is the
integrated GPU, but this ONNX Runtime build (`onnxruntime-windowsml` 1.30.0) does not simply take
adapter 0. So the change makes no difference here; it makes the choice explicit and the same on any
machine, and adds the second chance and the log line. It is also why D8's DirectML run was only a
little faster than the CPU: the GPU was the right one but waited on the worker's CPU-side preparation
of each frame (see the video throughput entry).

## Verification

- New tests, none needing a GPU (`tests/integration/test_ml_perception_handlers.py`): the high
  performance GPU is asked for first and named; a first choice that fails or lands on the CPU leads
  to DirectML's own choice; when both fail the provider fails (so the CPU variant runs); the
  environment override; a meaningless setting; the adapter named from a device list; a failing
  device listing never fails a load. Mutation: without the second choice, 5 of them fail.
- `tests/fixtures/directml_cannot_start.py` (the worker on a machine where DirectML cannot start, in a
  real process) recognises a provider given with options.
- On this machine: the worker's `load_session` named the RTX 4070 by default and the Intel GPU with
  `FACEIDENTIFY_DIRECTML_ADAPTER=0`.
