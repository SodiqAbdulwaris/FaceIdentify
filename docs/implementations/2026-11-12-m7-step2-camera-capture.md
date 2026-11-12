# M7 step 2: live camera frames over the pinned ffmpeg

- **Date:** 2026-11-12 (work began 2026-11-11)
- **Milestone / tracker IDs:** M7 step 2 · TST-071 (start, stop, reconnection of the capture), TST-072 (bounded frames)
- **Status:** done (the capture only; sessions use it from step 4)
- **Commits:** PR (number recorded when merged): `feat(cameras): capture live frames over the pinned ffmpeg`, `docs: record M7 step 2`

## What changed

- `backend/infrastructure/media/camera.py`: `list_devices` / `parse_devices` (DirectShow devices with their stable alternative name, audio left out); `device_input` (a device by its path when it has one, a 16 MB real-time buffer); `capture_command` (sampled with `fps` and bounded with `scale` **inside** ffmpeg, frames written as binary PPM on standard output); `classify` (a failed capture's log to `CameraNotFoundError`, `CameraInUseError`, `CameraAccessDeniedError` or `CameraStreamError`, each with its API code); `FfmpegFrameSource` (a reader thread keeps only the newest frame and counts the ones replaced before they were taken; `latest(timeout)` gives a frame newer than the last one, or raises why there is none; `stop()` kills and reaps the tool on every path).
- `backend/app/cameras/capture.py`: the frame-source port (`FrameSource`) and `LiveCamera`, which turns a source factory into frames and `Gap`s: a failure before the first frame is raised as it is; a later one is a gap, then reconnection with backoff (0.5, 1, 2, 4, 4 ... seconds) until `reconnect_timeout` (30 s, plan C7), then `CameraError` (`CAMERA_DISCONNECTED`); `close()` ends it from any thread.
- Tests: `tests/integration/test_camera_capture.py` (ffmpeg's synthetic source through the identical parser: sampling and scaling, a stalled consumer holding one frame and counting drops, the end of the stream, a stalled producer, a stop mid-stream, five kinds of corrupt frame, a missing DirectShow device, a tool that cannot start); `tests/unit/test_camera_live.py` (device parsing, classification, the reconnect rules on scripted sources and a fake clock).

## Why

[M7 plan](../plans/M7_PLAN.md) step 2, decisions C1 (the pinned ffmpeg with `-f dshow`, frames on a pipe), C2 (sampling in the subprocess, a buffer of one, newest wins, drops counted), C7 (reconnect with backoff, then close as disconnected) and C12 (no camera in tests).

## Decisions

> **Decision 2026-11-11 (delegated decision, M7 step 2):** frames are framed as binary PPM (`-c:v ppm -f image2pipe`) rather than raw RGB with a size read from ffmpeg's log: each frame carries its own size, so nothing depends on log text and a size change after a reconnect is read correctly. The cost is a 15-byte header per frame.

> **Decision 2026-11-11 (delegated decision, M7 step 2):** a failure before the first frame is the start's failure (the user can act on "in use", "access denied", "not found"); only after frames have flowed is a failure a gap followed by reconnection. A frame silence longer than 5 seconds is a failure like any other. Backoff 0.5, 1, 2, 4 seconds, then 4, inside the 30-second timeout of C7.

> **Decision 2026-11-11 (delegated decision, M7 step 2):** a stopped capture gives no frame it had already read: stopping is final.

## Verification

- `uv run pytest -q tests/unit/test_camera_live.py tests/integration/test_camera_capture.py` with the pinned FFmpeg: 37 passed; both new modules 100% covered (run three times, stable). `ruff`, `mypy`: clean.
- **This machine's camera (2026-11-11, no frame kept):** the pinned `ffmpeg -list_devices true -f dshow` lists one video device, "Integrated Camera" (1920x1080 at 30 fps, `yuyv422` or `nv12`), with its alternative name. Opening it (`-f null`, nothing written) succeeds but **delivers no frame**: `Error during demuxing: I/O error` before the first one, with every pixel format and buffer size tried. Windows lets desktop apps use the camera (`ConsentStore\webcam\NonPackaged` is `Allow`). A second program opening it at the same time gets the same error. The likely cause is the laptop's camera privacy shutter or kill switch (Lenovo); that is for the owner to check. The session code treats this correctly: a failure before the first frame ends the start with `CAMERA_DISCONNECTED` (`I/O error` is not one of the specific messages).
- The full backend gate ran on the branch before the PR (recorded in the PR).

## Open issues / follow-ups

- The camera's "no frames" state on this machine is the owner's to check (privacy shutter or kill switch, then the step 7 real-world check).
- `CameraInUseError` and `CameraAccessDeniedError` are mapped from ffmpeg's known log wording; neither could be produced on this machine, so their wording is unverified here.
