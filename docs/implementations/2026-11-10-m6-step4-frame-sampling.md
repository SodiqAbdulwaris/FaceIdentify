# M6 step 4 (first part): sampled frames over an ffmpeg pipe

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 4; TST-063 (timestamps); D4
- **Status:** done (the chunk checkpoints come with the video executor, step 5)
- **Commits:** PR (number recorded when merged): `feat(media): sample video frames by presentation time`

## What changed

- `backend/infrastructure/media/frames.py` (new): `sampled_frames(tools, path, width, height, rate=2,
  after_slot=-1)` runs one pinned `ffmpeg` that decodes from a position and writes raw RGB frames, as the
  Source shows them (rotation applied), to a pipe. Time is cut into slots of `1 / rate` seconds (D4: two a
  second) and the first frame of each slot is kept (`select`), so sampling is by presentation time, never by
  counting frames, and is the same whether a video is decoded in one go or resumed. Each frame's time comes
  from `showinfo` on standard error, read on a thread. Resuming after slot `k` seeks exactly to slot `k + 1`
  (`-ss` before `-i`, `-copyts`) and drops anything in a slot already given, so no frame is given twice.
  A failed decode, a pipe that ends inside a frame, or a frame without a time is a `CorruptVideoError`;
  stopping early kills and reaps the process.
- `tests/integration/test_video_frames.py` (new): clips made by the pinned build: times on a 25 fps and a 7 fps
  grid, resume giving exactly the remaining frames with the same pixels, another rate, rotation, a wrong size
  and a damaged file, an early stop, and the two missing-time paths. 100% line and branch coverage of
  `frames.py` from these tests alone.

## Why

M6 step 4: frames with exact presentation times, sampled at a configurable rate, decoded through the pinned
LGPL ffmpeg (D2 as confirmed in step 3; no PyAV).

## Decisions

Delegated (owner, 2026-11-09; reversible):

1. **Slots, not frame counts.** The kept frame of a slot is the first whose presentation time falls in it;
   a resumed decode reproduces the same choice because the slot grid is absolute (`-copyts`).
2. **One process per run segment**, not one per chunk: chunks are cut by the caller (step 5) from one
   stream; a resume starts a new process at the next slot.
3. **Hardware decoding stays off** (the plan's default).

## Verification

`uv run pytest -q tests/integration/test_video_frames.py` with the pinned build installed: 12 passed;
`frames.py` 100% covered. ruff, mypy (Windows and Linux): clean. Full gate: in the PR.

## Real containers (the owner's videos, read in place, 2026-11-10)

The owner allowed read-only use of his own video folder (369 files, 188 GB) to make probe and decode robust;
nothing from it (names, frames, faces) is in Git, a fixture or CI. Results, aggregates only:

- Containers and codecs: 127 Matroska HEVC 10-bit, 120 Matroska H.264, 100 MP4 HEVC, 9 MP4 H.264, 9 Matroska
  HEVC 8-bit, 2 AVI MPEG-4 Part 2, 1 MP4 HEVC 10-bit, 1 Matroska AV1 10-bit. Sizes up to 3840x1920.
- **Every one of the 369 probes and decodes** with the pinned LGPL build (four frames sampled five minutes in);
  none needed a codec the build lacks. The one uniform frame found was a black scene (later frames normal).
- Decode speed through the pipe at two frames a second, 60 s of video from five minutes in: MPEG-4 SD 319x
  real time, H.264 SD 180x, H.264 HD 115x, HEVC HD 59x, HEVC 10-bit HD 28x, AV1 10-bit HD 29x, **HEVC 10-bit 4K
  10.5x**. Detection on the real models runs at about 20x real time (41.7 frames a second, step 5), so decoding
  is never the slower stage.
- Because 4K frames exist, `sampled_frames(max_side=...)` scales a chosen frame down so its longer side is at
  most `max_side` (the executor uses 1920): a 4K chunk then holds a quarter of the memory, and the detector
  works at 640 pixels anyway. Boxes are normalised, so nothing downstream changes.

## Open issues / follow-ups

- Chunking, checkpoints and resume of a run: step 5's executor.
