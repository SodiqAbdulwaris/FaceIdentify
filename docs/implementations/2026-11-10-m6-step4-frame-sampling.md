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

## Open issues / follow-ups

- Chunking, checkpoints and resume of a run: step 5's executor.
