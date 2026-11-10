# M6 steps 4 and 5: chunked video runs, tracks, selection and batched worker turns (#242)

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 steps 4 (chunk checkpoints) and 5; #242; TST-063, TST-065, TST-067, TST-069; D4, D6
- **Status:** done (recognition and occurrences over time are step 6)
- **Commits:** PR (number recorded when merged): `perf(ml): let a batch of requests share one worker turn`,
  `feat(processing): process videos in checkpointed chunks`, `docs: record M6 step 5 and the batch measurement`

## What changed

- `PerceptionClient.turn()` (`backend/app/runtime/perception_client.py`): one worker turn for several requests;
  requests inside take no turn of their own, a nested `turn()` is the same turn, a client without a lease holds
  nothing. A cancellation (`cancellable`) is asked once, at the batch's turn.
- `ExecuteProcessingJob` (`backend/app/processing/execute_job.py`) processes a `VIDEO` source: the pinned ffmpeg
  decodes from the slot after the run's newest chunk checkpoint (`sampled_frames`, two frames a second, D4);
  frames go in chunks of `chunk_frames` (20: ten seconds). Per chunk: detection in batches of `frames_per_turn`
  (2) frames, each batch one turn inside `cancellable`; the tracker; selection; representation of the kept faces
  only, again a turn per batch of frames; then ONE transaction writes the chunk's observations (with
  `frame_index` and `timestamp_ms`), their representations and an `INTERMEDIATE` checkpoint (`video_chunks.py`:
  last slot, next sequence, tracker state, the chunk's track spans and observation-to-track pairs; no pixels).
  After the last chunk: recognition as for images, and FINAL with `tracks` (each track's observations, start and
  end time and frame). A frame larger than `max_pixels` fails the run before decoding.
- `backend/app/processing/tracking.py` (new, NumPy only, D6): greedy IoU association against each live track's
  box predicted by its last per-slot velocity (`min_iou` 0.2, a track ends after 2 empty slots), state as JSON
  so a track crosses a chunk boundary or a restart; `select_kept` keeps per track and chunk the best 3 by
  detection score times the square root of the face area, preferring faces at or above the quality gate.
- `ProcessSourceUseCase` accepts a video (`require_processable_source`); `RetryProcessingUseCase` still refuses a
  video run ("cannot be retried yet") until step 7 (D10).
- `benchmarks/worker_lease_stress.py --background-batch N`: the background detects video frames N to a turn.
- Tests: `tests/integration/test_execute_video_job.py` (the real executor, lease, decoder and database on a clip
  of painted squares, `tests/fixtures/video_pipeline.py`: chunks and tracks, one turn per batch, a search served
  after at most one batch, a cancellation seen at the next batch with nothing half-written, a crash then resume
  doing no frame twice with the tracks continuing, every failure settled `FAILED`, a clip with no faces, the
  retry refusal), `tests/unit/test_tracking.py`, `tests/unit/test_video_chunks.py`, the client's turn in
  `tests/integration/test_runtime_perception_client.py`, the benchmark's batch in
  `tests/unit/test_worker_lease_stress.py`.

## The batch measurement (#242)

`benchmarks/worker_lease_stress.py --real --bursts 3 --images 200 --background-batch N` on the installed
`buffalo_l` through the real pool and worker (the report records `DmlExecutionProvider`, no fallback), one
LFW photograph, face searches arriving every 400 ms on average (seeded), 2026-11-10:

| frames per turn | search wait p50 / p95 / max (ms) | background frames/s | search end to end p95 (ms) |
|---|---|---|---|
| 1 | 19.5 / 31.8 / 43.9 | 30.8 | 82.9 |
| **2** | **31.6 / 48.3 / 48.8** | **41.7** | **114.3** |
| 4 | 65.4 / 111.0 / 122.5 | 41.7 | 217.8 |
| 8 | 128.1 / 202.1 / 215.0 | 41.8 | 370.7 |

Simulated (40 ms detections) gave the same shape for the waits (p95 71, 131, 210, 384 ms) and no throughput
change, so the gain at 2 is the real worker's per-turn cost (activating the plan's supervisor, shared memory),
paid once per two frames. Reports (timings only): the shared notes folder, `bench-video-*.json`.

## Decisions

Delegated (owner, 2026-11-09; reversible):

1. **`frames_per_turn` = 2** (measured above): the throughput of larger batches with a search waiting at most
   about 50 ms at p95.
2. **Chunks of 20 sampled frames** (ten seconds at 2 fps): a checkpoint every ten seconds of video, pixels of
   one chunk in memory (about 120 MB at 1080p; larger frames are scaled down, decision 7).
3. **Tracker (D6):** IoU 0.2 against a constant-velocity prediction, 2 slots of grace; no embedding in
   association (embeddings exist only for kept faces). To be checked on owner video in step 8 (D8).
4. **Selection:** 3 per track and chunk, score times square-root area, at or above the decision policy's
   quality gate when any is; only those are embedded and recorded.
5. **Checkpoint and FINAL payloads** (spec text, D1): recorded in `PERSISTENCE_IMPLEMENTATION.md` section 15.
6. **A video run is not retried until step 7** (D10 builds resume from the checkpoint).
7. **Frames are scaled to a longest side of 1920** (`VideoProcessing.max_side`) before detection: the owner's
   library has 3840x1920 HEVC (step 4 entry), and a 20-frame chunk of 4K would otherwise hold about 440 MB.

## Verification

- `uv run pytest -q tests/integration/test_execute_video_job.py tests/unit/test_tracking.py
  tests/unit/test_video_chunks.py tests/integration/test_runtime_perception_client.py
  tests/integration/test_execute_processing_job.py tests/integration/test_process_source.py
  tests/unit/test_worker_lease_stress.py`: all pass; `tracking.py`, `video_chunks.py`, `pending_output.py`,
  `process_source.py` 100%; the rest covered by the full suite (gate in the PR).
- ruff, mypy (Windows, Linux): clean.

## Open issues / follow-ups

- Occurrences over time and the track-level rule (D7): step 6. Pause, resume, admission, retry: step 7.
