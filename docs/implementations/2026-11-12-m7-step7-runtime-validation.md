# M7 step 7: runtime validation, benchmarks, and what is left for the owner at the camera

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M7 step 7 · TST-072 to TST-077; TST-071 (real camera)
- **Status:** done, except the real-world check at the camera, which only the owner can do (below)
- **Commits:** PR (number recorded when merged): `test(cameras): measure a camera session and re-assert provider agreement`, `docs: record M7 step 7`

## What changed

- `benchmarks/camera_soak.py`: per provider, the time of a face search and of one worker turn (p50, p95), and a **soak**: the whole application in one process on a fresh scratch library (the model package and policy copied, nothing of the owner's written), a real session reading a synthetic clip (an LFW photograph shown 3 s in every 10, black otherwise) through the real ffmpeg capture pipe at camera pace, for 10 minutes, with a face search every 20 s (interactive class) and a background detection every 0.5 s (batch class) on the same worker. Writes a JSON report (frames, dropped, encounters, per-class lease waits, memory, indexed faces). Local only.
- `tests/e2e/test_provider_agreement.py`: the same faces embedded on the CPU and on DirectML through the production client and worker agree to within 1e-5 (1 - cosine, computed in float64), with no fallback on either side. `e2e` (excluded by default; the weights never enter CI); `FACEIDENTIFY_E2E_LOCAL_MODELS` names the models folder so a worktree needs no link to it.

## Results (this machine: Windows 11, 32 logical CPUs, NVIDIA GeForce RTX 4070 Laptop GPU; 2026-11-12)

Reports are in the Git-ignored scratch folders of the run and were deleted with them; the numbers are recorded here.

**Latency** (one face picture, 20 searches after a first one that loads the model):

| Provider | First search | Search p50 / p95 | One worker turn p50 / p95 |
|---|---|---|---|
| DirectML (`onnxruntime-windowsml` 1.30, shipped) | 5.3 s | 0.25 s / 0.31 s | 0.007 s / 0.019 s |
| CPU | 6.4 s | 1.07 s / 1.42 s | 0.31 s / 0.52 s |
| CUDA (`onnxruntime-gpu` 1.23.2, developer only, `FACEIDENTIFY_ORT_GPU_DIR`) | 6.3 s | 0.25 s / 0.31 s | 0.019 s / 0.040 s |

**Soak, 10 minutes, DirectML:** 2,906 frames read of 3,000 sampled (5 per second), 94 dropped (3.1%), **60 encounters recorded of the 60 visits** in the clip, ended `STOPPED`; 29 searches, p50 0.31 s, p95 0.40 s; lease waits: live p50 0.015 ms, p95 2.5 ms (max 4.4 s, the worker's start); interactive p95 43 ms; background 1,098 turns, p95 35 ms (batch work keeps moving under a camera); memory 118.8 MB at the start, 122.5 MB at the end (peak 141.8 MB), growth 3.7 MB; 178 faces indexed (about 3 per encounter, C3).

**Soak, 10 minutes, CPU** (DirectML did not start in that run and the CPU took over, recorded as `provider_fallback: ACTIVE` and in the run's segments; the same DirectML run alone a few minutes later started normally): 2,369 frames, 632 dropped (27%: the CPU cannot keep 5 per second with searches and batch work beside it), 61 encounters, searches p50 1.0 s, p95 2.5 s; interactive p95 0.60 s; background p95 0.51 s; memory growth 6.1 MB; 179 faces indexed.

**Agreement DirectML against CPU** (`test_provider_agreement.py`, the 4 pictures of `local-models/images`, 5 faces): largest 1 - cosine 5.5e-9, largest element difference 1.5e-7 (the 2026-10-16 record over 686 faces: 1.25e-6). Passed.

## Tracker

- **TST-072 `PASSING`:** the backlog stays bounded (a buffer of one, newest frame wins; 3% of frames skipped on DirectML, 27% on the CPU, never a growing queue; the live class's waits above), plus the step 2 and 3 tests.
- **TST-073 `PASSING` (developer only):** CUDA re-run inside the benchmark (above); CUDA is not shipped and not a release gate (decision 2026-10-15).
- **TST-074 `PASSING` on this machine only:** DirectML ran the soak and the agreement test on this NVIDIA GPU. AMD, Intel and machines without DirectX 12 are not verified (one machine is available).
- **TST-075 `PASSING`:** the CPU takes over visibly: the step 4 test of a fallback mid-session (detection and embedding), the existing DirectML-cannot-start tests, and the real run above where it happened and was recorded.
- **TST-076 `PASSING`:** a provider changes nothing the space depends on (the agreement test); the policy stays bound to its representation space, which no provider changes (the catalog's design, tested since M3).
- **TST-077 `PASSING`:** the baselines above, reproducible with `benchmarks/camera_soak.py`.
- **TST-071 stays `IN_PROGRESS`:** every automated part passes (steps 1 to 6), but the real camera on this machine gives no picture (below), so start, stop and reconnection with a real camera are not verified.

## The real camera on this machine (validation that needed no one in front of it, 2026-11-11 and 2026-11-12)

- The pinned `ffmpeg` lists one DirectShow video device, "Integrated Camera" (1920x1080 at 30 fps, `yuyv422` or `nv12`), with its stable path.
- Opening it succeeds, but **no frame ever arrives** (`Error during demuxing: I/O error` before the first one), with every pixel format and buffer size tried, and Windows allows desktop apps to use the camera (`ConsentStore\webcam\NonPackaged` is `Allow`). The application reports this correctly: a session started on it ends `FAILED` with `CAMERA_DISCONNECTED`, and the screen says to check that the camera is plugged in and that its privacy shutter or camera key is not covering it.
- No frame was captured, recorded or kept by any of these checks.

## What only the owner can do (the real-world check, plan step 7)

1. **Make the camera give a picture:** open the laptop's camera privacy shutter, or press the camera on/off key (often F8 or a key with a crossed-out camera on Lenovo laptops), then check the Windows Camera app shows a picture.
2. In FaceIdentify: **Cameras**, choose "Integrated Camera", name it, **Add camera**, then **Start**. Check the "Camera on" mark appears at the top of every screen and the live picture shows a box around your face.
3. **A visit by you** (someone you have named in the app): stand in front of the camera for a few seconds, then leave for more than 5 seconds. In **History**, one visit should appear under your name.
4. **A visit by someone unknown** (with their consent): one visit, shown under "Not recognised", and no new person created.
5. **Disconnect and reconnect:** close the shutter (or unplug a USB camera) while it runs: the status should show "Reconnecting"; open it again within 30 seconds: it carries on; leave it closed longer: the session ends with the camera message.
6. **Crash and recovery:** while a session runs, end the app from the Task Manager, start it again: the camera is off (nothing restarts on its own), the visits recorded before stay, and a new session starts normally.
7. **Search with the camera:** with a session stopped or running, **Search with this camera** while facing it: your name should come back.
8. **Delete:** delete one visit, then a day; confirm they are gone. Then tell the agents the result (it closes TST-071 and the M7 real-world check).

Optional tuning for the check: the 5-second encounter gap and the 5 frames per second (plan section 9, item 4) are application defaults; if visits are split or merged wrongly, say so.

## Decisions

> **Decision 2026-11-12 (delegated decision, M7 step 7):** the soak's "camera" is a synthetic clip of a public LFW photograph read through the real capture pipe at camera pace, so the measurement needs no person and no camera; the real camera is the owner's check.

## Verification

Commands as in the benchmark's docstring; `uv run pytest -m e2e tests/e2e/test_provider_agreement.py` with `FACEIDENTIFY_E2E_LOCAL_MODELS`: 1 passed. The benchmark is not part of CI.
