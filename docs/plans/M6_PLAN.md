# M6 plan: movies and scheduling (approved)

**Status:** **approved by the owner on 2026-10-21** (drafted 2026-10-16 during the unattended overnight
run). The owner decided D1 to D10 as recommended and added D11 and D12; the outcomes are recorded in
section 7. Nothing here is built yet. **Scope:** tracker milestone M6 (TST-060 to TST-070) in
[`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md), the Roadmap's Phase G
(source reprocessing, issue #180) and video phase ([`Roadmap-Plan.md`](Roadmap-Plan.md) sections 66
to 70), and the worker arbitration that long runs need (issue #175). **Milestone gate (tracker):**
"Movie processing can be interrupted and recovered without corrupting identity memory."

This plan sequences work; it changes no spec. Where a step needs a spec change (a new table, route or
contract), the step says so, and that step's PR proposes the exact text for the owner to approve there
(D1).

## 1. Where things stand (2026-10-16)

> **Update 2026-10-21:** M5 is complete: the owner declared it on 2026-10-21 as of main `a778d81`
> ([entry](../implementations/2026-10-21-m5-complete.md)), and approved this plan the same day. The first
> bullet below is the 2026-10-16 state, kept as written.

- M5 is close to its definition of done (`M5_PLAN.md` section 5): real `buffalo_l` models on DirectML
  or the CPU, assisted and automatic recognition (0.45 / margin 0.10), naming, corrections, merge,
  split, recycle, delete, forget, name and face search. Images only.
- Already in place for M6, built and tested in M2 and M3 on images:
  - `sources.kind` accepts `VIDEO` (`backend/app/sources/models.py`), and observations already carry a
    frame index and time for video (`backend/app/memory/models.py`).
  - Jobs with a state machine that includes `PAUSING`, `PAUSED`, `CANCELLING`, `INTERRUPTED`
    (`backend/app/jobs/models.py`), an integer priority rank and an `INTERACTIVE` priority;
    `JobType.REPROCESS_SOURCE` exists but nothing creates it.
  - Processing runs, execution segments (provider provenance and fallback intervals), durable
    `INTERMEDIATE` and `FINAL` checkpoints, frozen configuration snapshots, startup recovery of
    interrupted runs, retry and cancellation at safe boundaries (`backend/app/processing/`,
    `backend/app/recovery/`).
  - One persistent ML worker behind a supervisor, and an index coordinator that converges USearch with
    SQLite.
- Not in place: any video decoding (no FFmpeg or PyAV dependency yet), tracking, observation selection,
  occurrences that span time, pause and resume as user actions, reprocessing (#180), and arbitration of
  the one worker between interactive queries and long runs (#175).

## 2. Constraints that shape the order

- **Reprocessing comes before video** (Roadmap section 67: "Only after recognition, naming,
  correction, merge, split, forget, reprocessing are trustworthy should we add video"). #180's design
  is locked (owner, 2026-10-14: versioned runs with atomic supersession) and explicitly deferred to M6.
- **One heavy movie job at a time** (processing spec section 8), with internal parallelism allowed.
- **Chunk boundary is not an identity boundary** (spec section 13): tracks crossing a chunk are
  reconciled.
- **Locked media stack:** FFmpeg + ffprobe are canonical, PyAV gives frame and timestamp access, direct
  FFmpeg pipes are allowed where PyAV fails a flow; **OpenCV is not a baseline** (decision 2026-10-02)
  and is introduced only for a demonstrated need (tracking is named as one possible need).
- **Query is not ingest; ML is evidence, not truth; human decisions win** (Roadmap sections 7 and 8,
  identity model). Reprocessing must never silently overwrite names, corrections, merges or splits.
- **Worker arbitration (#175, locked 2026-10-14):** cooperative priority scheduling with starvation
  protection, no preemption inside an inference, bounded checkpointable batches with yield
  boundaries, one resident worker.

## 3. Steps

Each step is one or more small PRs, each with its own implementation entry and an independent
review, as in M5.

### Step 1. Reprocessing images: versioned runs with atomic supersession (#180, Roadmap Phase G)

Build the locked design for images first, where every other part of the pipeline is already proven.
- `REPROCESS_SOURCE` creates a new run (V2) while V1 stays authoritative; V2 output is PENDING and
  invisible to search, counts and identity decisions.
- On success, one transaction switches the source's authoritative generation and marks V1's derived
  observations, representations and occurrences `SUPERSEDED`, with a supersession link and time. On
  failure or cancellation V1 stays current.
- Index reconciliation after commit through the existing coordinator; queries filter on the
  authoritative generation until it converges.
- Human-authored associations carried over only through a trustworthy face correspondence; ambiguous
  ones go to review (decision D3).
- Needs: a schema revision (generation pointer, supersession link, `SUPERSEDED` where the tables do not
  allow it) and a route (`POST /sources/{id}/reprocess`), both spec changes (D1).
- Tests: the seven acceptance tests in #180's decision, including crashes before, during and after
  activation, and forget or erasure surviving reprocessing.
- Tracker: TST-061, TST-064, TST-067 (their image halves).

### Step 2. Worker arbitration (#175) and one worker process (#221)

A lease at the perception client boundary: interactive requests first at the next safe boundary, FIFO
within a class, bounded consecutive interactive grants so background work progresses, cancellation and
shutdown at boundaries, release in `finally`, no database transaction or file lock held across an
inference. Measured, not invented: per-class wait and execution times and queue depth are logged, and
the fairness parameter starts at 3 consecutive interactive grants and changes only on benchmark
evidence (D5). Needed before long videos, useful for images now (a face search during a large import).
- The pool owns exactly one worker process for all plans (#221, an owner-accepted deferral from #213,
  moved into this step by D11). Today the pool keeps one worker per plan; the lease then arbitrates
  across plans instead of per plan.
- Acceptance: #175's remaining acceptance tests (batch yields for long runs, queued cancellation, the
  measured fairness parameter) and, for #221, a test that the pool never holds more than one live worker
  process across plans, shutdown and crash recovery included.
- Tracker: TST-069 (first half). (TST-068, one heavy movie pipeline at a time, is a job-admission rule, not
  this lease: step 7 owns it.)

### Step 3. Video sources: import and probe

- Import a video as a `VIDEO` source (managed or referenced, as images are), with ffprobe metadata
  (duration, frame rate, streams, rotation) stored as source metadata; refuse unsupported or damaged
  files clearly.
- Adds the FFmpeg runtime and PyAV dependency (D2: how FFmpeg is obtained and licensed, LGPL build).
- Thumbnails from a key frame.
- Tracker: TST-063 (metadata half).

### Step 4. Decode, sample and chunk

- PyAV decode into bounded chunks with exact timestamps (presentation time, not frame counting),
  sampling at a configurable rate (D4), hardware decode left off by default.
- A chunk is a checkpoint boundary: `INTERMEDIATE` checkpoints record the last completed chunk, so a
  crash or pause resumes there, never from the start and never twice.
- Tracker: TST-063, TST-065, TST-066, TST-067.

### Step 5. Detect, track and select

- Detection per sampled frame with the existing SCRFD contract.
- A tracker that links detections across frames into tracks, built with NumPy (IoU and landmark
  distance association, a small motion model) unless measurement shows a need for more (D6). Track
  continuity across chunk boundaries reconciled.
- Observation selection: keep a few good-quality, diverse observations per track (detection score, face
  size, pose from landmarks); embed only those. No crop is retained for every frame.
- Tracker: TST-063 (segment correctness), TST-069.

### Step 6. Recognition and occurrences over time

- Track-level recognition: embeddings of the selected observations vote under the existing policy (the
  same 0.45 / margin 0.10 point applies per representation; a track-level rule needs its own evidence,
  D7).
- Occurrences that span time: "Person X appears 00:04:21 to 00:04:47" (Roadmap section 69), several
  observations supporting one occurrence.
- Movie-local reconciliation of unknown tracks before comparing with global memory; ambiguous goes to
  review, never to an automatic new identity (the 2026-10-08 rule that abstain is not new identity).
- Tracker: TST-061, TST-070.

### Step 7. Pause, resume, cancel, and the movie workflow end to end

- Pause and resume as user actions (routes and screen controls) on checkpoint boundaries; cancel keeps
  committed work consistent.
- Desktop: a video source screen with a timeline of appearances, progress and ETA (spec section 15).
- End to end: import a movie, process it, pause, restart the app, resume, finish, and check identity
  memory (Roadmap section 70), with the process killed at each stage as in M3.
- Reprocessing a video (step 1's rules on video).
- One heavy movie job at a time (processing spec section 8) enforced at job admission, not only by the
  worker lease: a second movie stays `QUEUED` while the first runs, tested with two queued movies
  (and with an image job and a face search running alongside, which may).
- Retry of a failed video run (the video half of TST-064): today `RetryProcessingUseCase` refuses video
  and starts a fresh run. Decide (D10) whether a video retry resumes from the last valid checkpoint or
  starts over, and test that neither path duplicates committed observations, occurrences or index
  operations.
- Tracker: TST-060, TST-062, TST-064 (video half), TST-065, TST-066, TST-067, TST-068, TST-070.

### M6 real-world check

A small set of videos the owner may use (D8), processed on DirectML and on the CPU, with timings, the
appearance list compared by hand for a few people, and a crash-and-resume run.

## 4. Dependencies and blockers

- Step 1 has no dependency beyond M5. Steps 3 to 7 depend on step 1 (Roadmap order) and step 2 (which
  includes #221, the single worker process, D11).
- Step 3 adds a new dependency and a runtime binary (decided by D2: the locked stack, a pinned LGPL
  FFmpeg and PyAV). The exact builds' licences, PyAV's bundled FFmpeg included, are inspected and
  recorded in `docs/research/licensing-and-commercialization.md` before step 3 merges.
- Spec changes gate steps 1, 3, 6 and 7; each step's PR proposes its exact spec text for the owner to
  approve there (D1).
- Test videos (the owner's own, D8) gate the real-world check; fixture videos for CI can be generated (frames built from the existing image
  fixtures, or FFmpeg's test sources), never from biometric data.

## 5. Tracker IDs and definition of done

M6 is done when TST-060 to TST-070 are `PASSING` with the evidence their rows ask for, #180, #175 and #221
are closed with their acceptance tests, the real-world check is recorded, and the milestone gate
holds: a movie interrupted at any stage and recovered leaves identity memory uncorrupted (no duplicate
occurrence, no lost or resurrected evidence, human decisions intact), shown by tests that kill the
process at each stage.

## 6. Risks

- **Video volume:** a two-hour film at 25 fps is 180,000 frames; sampling, selection and bounded
  queues decide whether this runs in minutes or hours. Measure on the target laptop early (step 4).
- **Tracking quality** decides occurrence quality; a weak tracker splits one person into many tracks or
  merges two. Mitigation: track-level evidence stays evidence, movie-local reconciliation, review.
- **Reprocessing and human decisions:** the face-correspondence rule (D3) is the hardest part of step
  1; getting it wrong silently moves a confirmed face. Conservative default: ambiguous means review.
- **FFmpeg licensing and packaging:** an LGPL build, dynamically linked, its licence recorded; GPL
  components (x264 and similar) excluded. A packaging concern for M8, a dependency decision now.
- **Worker contention:** without step 2, a long video blocks face search for its whole duration.
- **Checkpoint volume:** per-chunk checkpoints in SQLite must stay small (positions and ids, not
  pixels).

## 7. Decisions (recorded 2026-10-21)

> **Decision 2026-10-21 (owner):** "I accept all twelve M6 recommendations (D1 to D12 as you laid them
> out) and approve the M6 plan." D1 to D10 are the ten decisions drafted on 2026-10-16, decided as
> recommended (D5 reworded below); D11 and D12 were added on 2026-10-21. Recorded in
> [the implementation entry](../implementations/2026-10-21-m6-plan-approved.md).

| # | Decision | Outcome (owner, 2026-10-21) |
|---|---|---|
| D1 | Spec changes M6 needs: a generation pointer and supersession link (identity model, ERD, persistence spec), `REPROCESS_SOURCE` and pause/resume routes (API spec), video source metadata | Approved per step: each step's PR proposes the exact spec text for the owner to approve there. No spec text is added by the plan itself |
| D2 | How FFmpeg and ffprobe are obtained (both locked in `tech-stack.md` section 6 and Roadmap section 68) | Keep the locked stack: a pinned LGPL FFmpeg build (ffmpeg + ffprobe) as a runtime package, plus PyAV for frames, with no GPL components (x264 and similar). The exact builds' licences, PyAV's bundled FFmpeg included, are inspected and recorded in `docs/research/licensing-and-commercialization.md` before step 3 merges |
| D3 | Reprocessing: what counts as a trustworthy face correspondence between V1 and V2 for carrying human decisions over | A human decision carries over only within the same compatible `RepresentationSpace` (processing invariant 36.9), the same source, box IoU >= 0.7 and embedding cosine >= 0.9, one-to-one. Anything else goes to review: a model or preprocessing change, or a missing vector. Reasoning: the DirectML re-measure showed same-model embeddings within 1.25e-6, so true correspondences sit near 1.0, and no stranger scored above 0.402 |
| D4 | Default video sampling rate | 2 frames per second for detection, configurable; adaptive sampling only if measured to help |
| D5 | Worker fairness parameter | Keep 3 consecutive interactive grants (built in #213, confirmed in the 2026-10-16 overnight decisions) as the starting value. Step 2 benchmarks it, and it changes only on measured evidence |
| D6 | Tracker: NumPy-only association, or OpenCV | NumPy-only first (IoU, landmarks, embedding when available); OpenCV only for a measured need |
| D7 | Track-level automatic acceptance | Reuse the per-face 0.45 / margin 0.10 point on each selected observation and require them to agree. A track-level rule is measured later, on owner-verified video |
| D8 | Test videos for the real-world check | The owner's own videos, kept local and Git-ignored like the photographs. CI fixtures are generated, never biometric |
| D9 | Whether reprocessing (step 1) ships in M6 | Yes, in M6 as step 1 (Roadmap order and #180's decision both put it before video) |
| D10 | Retry of a failed video run | Resume from the last valid checkpoint when the run's frozen snapshot is still runnable (same models and settings); otherwise start a new run, leaving the old run's committed output untouched. Both paths are tested for no duplicates |
| D11 | #221 (the pool owns exactly one worker process, an owner-accepted deferral from #213) | Goes into M6 step 2, alongside #175's remaining acceptance tests |
| D12 | The M6 plan | Approved |

## 8. Not in this plan

Live cameras (M7), CUDA or other GPU work beyond what M5 shipped (M7), packaging the FFmpeg runtime in
an installer (M8), learned decision models, retraining, automatic merges, and PDF face search (#176).
