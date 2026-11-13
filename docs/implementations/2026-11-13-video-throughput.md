# Video throughput: where the time goes, and the worker preparing each frame once

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M6 (follow-up to the D8 real-world check; the owner asked how to lift
  3.4 to 4.0 times real time)
- **Status:** done
- **Commits:** PR (number recorded when merged): `perf(ml): prepare each video frame once, with
  identical inputs`

## How it was measured

One episode of the D8 sample (2,466 s of 720p HEVC; numbers only, as in the D8 entry), the real
host and models on a scratch state and library, a fresh library per run. A throwaway copy of
`execute_job.py` (never committed) timed each stage of the video path with `time.perf_counter`, and
`py-spy` (run with `uvx`, not a project dependency) sampled the host and the ML worker for 60 s.
Nothing else heavy was running: total CPU averaged 19% over the DirectML runs (this measurement
included), on an i9-14900HX with 32 logical processors, on mains power. The very first run (607 s)
had py-spy attached for its first minute and is left out; one later run of the previous code (363 s)
overlapped a test run of mine and is left out too. Each figure below is the mean of two clean runs.

## Where the time goes (DirectML on the RTX 4070, before)

The ML worker was busy about 80% of the time and the host about 20%: the single worker is the bound,
not decoding.

| Stage (whole episode) | Before | After | Change |
|---|---|---|---|
| Detect calls (4,937 frames) | 144.0 s | 125.3 s | -13% |
| Represent calls (3,211 frames with kept faces) | 92.9 s | 70.0 s | -25% |
| Per-chunk transaction (247 chunks) | 18.4 s | 18.7 s | +1% |
| Waiting for decoded frames | 15.7 s | 15.4 s | -2% |
| Cancel checks per batch | 4.8 s | 4.7 s | -2% |
| Waiting for the worker's turn (detect, represent) | 3.6 s | 3.4 s | -3% |
| Tracking and selection | 0.8 s | 0.8 s | -2% |
| Pause and cancel checks per chunk | 0.5 s | 0.5 s | 0% |
| Recognition, decisions, finalising (end of run) | 9.4 s | 5.4 s | (noise: unchanged code) |
| **Whole video path** | **291.0 s** | **245.1 s** | **-16%** |
| **Video seconds per second** | **8.5** | **10.1** | |

Inside the worker (py-spy, share of its busy time): a detect call was about 50% `letterbox` (the
PIL resize to the detector's 640 px and a float canvas normalised, transposed and copied) and 41%
inference; a represent call was 70% inference, 15% alignment and about 20% copying the full frame
out of shared memory and converting it to an image, **once per face** (2.3 faces per frame).

The GPU itself is quick (per call: detect about 6 ms, embed about 4.5 ms on DirectML; see the
DirectML adapter entry) but waits for the worker's CPU-side preparation of each frame, and a
laptop GPU clocks down in those gaps: the same inference took 12.4 ms instead of 6.7 ms with 30 ms
of CPU work between calls. So the CPU-side preparation costs twice.

## What changed (identical inputs to the models)

- `detection.letterbox`: a pixel has 256 values, so `(value - mean) / std` is computed once per value
  in float32 (the same operation the canvas did) and looked up straight into the channel-first
  tensor; the padding is the same table's value for 0. The resize is untouched.
- `alignment.align_image` and `image_of`: the faces of one frame share one converted image;
  `perception_handlers.represent` reads and converts each frame once per request, not per face.

**Equality:** unit tests pin both against the previous code bit for bit (`letterbox` on five frame
sizes, alignment on three faces of one frame). End to end, a run with the change against one without
on the same episode: the same 7,264 kept faces, every vector and detection score bit-identical, the
same 3,938 tracks, the same decisions.

## CPU

The same episode with the CPU provider (one run each; the CPU run is bound by inference, 51 ms per
face embedded, so preparing frames matters less):

| | Detect calls | Represent calls | Whole video path | Video seconds per second |
|---|---|---|---|---|
| CPU, before | 274.1 s | 396.5 s | 719.4 s | 3.4 |
| CPU, after | 258.9 s | 383.0 s | 690.2 s | 3.6 |

Bit-identical outputs again (the same 7,264 faces, vectors, scores, 3,938 tracks and decisions).

**One table for the owner** (this episode, whole video path, video seconds per second):

| Provider | Before | After |
|---|---|---|
| CPU | 3.4 | 3.6 |
| DirectML, default adapter (the RTX 4070 on this laptop) | 8.5 | 10.1 |
| DirectML, high-performance GPU asked for explicitly | same adapter as the default here | same |

The live library still runs on the CPU (its package predates the DirectML variants; moving it needs
the package-upgrade path, see the D8 entry's follow-ups), so on the owner's library the measured
DirectML gain is about 2.8 times (3.6 against 10.1) once that path exists.

## What was not changed, and what would help next

Recommendations, each changing results or needing a decision (not done):

- **Prepare frames in the host, beside the worker.** The resize to 640 px (about 11 ms a frame) could
  run in the host's decoding thread while the worker infers, and send a frame a quarter of the size.
  The boxes would then be computed against the small frame and rounded slightly differently, so the
  output would no longer be bit-identical (decisions very likely the same; it needs that check).
- **Keep one frame for detect and represent.** The worker receives each frame twice (about 2.8 MB,
  once per call). Keeping a chunk's frames in the worker between the two calls needs a protocol
  change in the worker and the supervisor, which other work is changing now.
- **Overlap the host's work with the worker's.** Decoding, the chunk transaction and the checks
  (about 40 s here, 15%) run while the worker waits; a one-chunk prefetch would hide most of it.
- **Lower sample rate, a smaller `max_side`, or hardware decoding**: these change results and are
  the owner's call.
- Batching faces into one embedder call does not help: on the CPU it is bit-identical but no faster
  (49, 82, 138 ms for 1, 2, 4 faces), and DirectML refuses a batch with this model (its
  BatchNormalization is fixed to one).
