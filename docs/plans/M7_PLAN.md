# M7 plan: live cameras

**Status:** drafted 2026-11-09 by the agent under the owner's delegation (2026-11-09: "i'll leave the
rest of the decisions entirely to you"; scope "Everything through M8"). Every decision in section 8 is a
**delegated decision**: the owner may reverse any of them, and each is written so that reversing it
costs one step, not the plan. Nothing here is built. **Scope:** tracker milestone M7 (TST-071 to
TST-077) in [`TESTING_IMPLEMENTATION_TRACKER.md`](TESTING_IMPLEMENTATION_TRACKER.md) and the Roadmap's
camera phase ([`Roadmap-Plan.md`](Roadmap-Plan.md) section 71). **Milestone gate (tracker):** "Included
camera and runtime functionality satisfies its correctness and compatibility requirements."

The plan sequences work and changes no spec. Each step that needs a spec change says so, and that
step's PR proposes the exact text, which is independently reviewed and recorded as a dated delegated
decision (the arrangement M6's D1 now has, see [`M6_PLAN.md`](M6_PLAN.md)).

## 1. Where things stand (2026-11-09)

- **Built and relied on:** the one persistent ML worker behind a supervisor, and the worker lease that
  takes it in turns (interactive face search first, three in a row at most before a waiting background
  request; `backend/ml/supervisor/lease.py`); DirectML then CPU inference with a visible fallback, and
  CUDA for the developer only; recognition under the owner-approved point (0.45 / margin 0.10, no
  automatic new identity); the permanent-deletion and erasure paths (M5 steps 4b and 4c); jobs, runs,
  frozen snapshots, startup recovery, and the WebSocket event connection.
- **Not built, and M7 depends on it (M6, approved, in progress):** FFmpeg as a pinned LGPL runtime
  (recommended by the D2 record, pending confirmation, `docs/research/licensing-and-commercialization.md` section 4.1), the NumPy
  tracker and observation selection (M6 steps 4 and 5), track-level recognition and time-spanning
  occurrences (M6 step 6), the single worker process across plans and the measured lease (M6 step 2).
- **Nothing camera-specific exists.** `SourceKind` has `IMAGE` and `VIDEO` only
  (`backend/app/sources/models.py`); `JobType` has no camera type (the specs name
  `PROCESS_CAMERA_SESSION`); the schema of `PERSISTENCE_IMPLEMENTATION.md` has no camera tables
  (revision 0001 says so: "no cameras"); `backend/app/cameras/` is an empty package; the API spec names
  a `cameras` resource family and a future `camera.*` event namespace but defines no route.
  [`ERD.md`](../specs/ERD.md) describes `camera_source_metadata`, `encounter`, `appearance` and `track`
  conceptually only.
- **The hardware rows of M7** (TST-073 to TST-077) mostly need evidence and tests rather than product
  code: DirectML is shipped and was measured on this machine on 2026-10-16, CUDA is developer-only
  (decision 2026-10-15), the CPU fallback exists.

## 2. What the specs ask for (the whole scope; nothing is added to it)

From [`product-definition-and-requirements-v1.md`](../specs/product-definition-and-requirements-v1.md)
sections 5.4, 9, 10.4 and FR-003, FR-008, FR-009, FR-056 to FR-059, NFR-009,
[`processing-architecture-v1.md`](../specs/processing-architecture-v1.md) sections 7, 14 and 25, and
[`identity-and-memory-model-v1.md`](../specs/identity-and-memory-model-v1.md) section 16:

1. A configured camera is a `CAMERA` source. It detects several people, tracks them while visible,
   recognises remembered identities, records encounters and keeps selected face observations.
2. Continuous recording is **off by default**; encounter history and selected face snapshots are **on**;
   automatic deletion is **off**; the user can delete an encounter, selected history, a day or time
   range, or all history of a camera.
3. Live work optimises bounded latency over completeness: a shallow frame buffer and stale frames
   dropped rather than a growing backlog; the live class outranks batch work at safe boundaries without
   starving it.
4. A camera session is long-lived, not a 0 to 100% job; after an interruption or a crash it is closed
   or marked interrupted, a new session begins later, and **continuity across unobserved time is not
   fabricated**.
5. Memory is not updated from every frame: evidence is consolidated when an encounter closes.
6. A user can present a face to a configured camera and search the library with it (10.4).

## 3. Constraints that shape the order

- **Locked stack** (`.agents/rules/scope.md`): no new package manager, no second worker, no OpenCV as a
  baseline (decision 2026-10-02; C1 needs none); FFmpeg is the media foundation.
- **One worker** (`docs/research/tech-stack.md` section 10): live work shares it with movie processing
  and searches through the lease. The spec's escape hatch (a second specialised worker) is taken only
  on measured evidence, and not by this plan.
- **The 2026-10-08 owner rule stands:** abstain is not new identity. The product spec's 6.1 ("may
  autonomously create a new candidate identity") is older and more general; the owner's later, more
  specific decision wins, so a live camera never creates an identity automatically either (C5).
- **Query is not ingest; ML is evidence, not truth; human decisions win.** Nothing a camera does may
  overwrite a name, a correction, a merge or a split.
- **Offline operation (SEC-005) and the refusal of network targets (#174):** the application makes no
  network connection to do its work, so a camera is a device on this computer (C2).
- **Privacy:** a camera is the first input that records people who did not choose to be recorded
  (visitors, family). Defaults are the specs' (nothing recorded, nothing automatic) plus the small
  protections in C4.
- **Windows camera privacy:** desktop apps need "Let desktop apps access your camera" turned on in
  Windows settings. This is an assumption about Windows, not verified here; the screen must say so
  when the camera cannot be opened.

## 4. Steps

Each step is one or more small PRs, each with its own implementation entry and an independent
read-only review, as in M5 and M6.

### Step 1. Spec text, schema and the camera source (no capture yet)

- **Spec proposal in the PR** (delegated decision, reviewed): the `CAMERA` source kind and
  `camera_source_metadata` (device identity and a display name, nothing else); that a camera session is
  a `PROCESS_CAMERA_SESSION` job with one processing run, so the frozen policy, models and settings are
  recorded per session; that an **encounter is an `Occurrence` of kind `TRACK`** on a camera source
  (C3), so M7 adds **no** `encounter`, `appearance` or `track` tables (the ERD stays conceptual, as M6
  already assumes for movies); the camera routes of section 5 and the `camera.*` events; the settings
  keys of C2, C7 and C8.
- One Alembic revision: `CAMERA` in the source-kind check, `camera_source_metadata`, the job type
  `PROCESS_CAMERA_SESSION`. Migration, downgrade guard and persistence tests as in earlier revisions.
- Tracker: TST-071 (the model half).

### Step 2. Capture: one frame source over the pinned FFmpeg

- A frame-source port with two adapters: the real one runs the pinned `ffmpeg` as a subprocess with
  DirectShow input (`-f dshow`) and raw video on a pipe (C1); a test adapter replays a generated clip or
  a scripted fake. Device listing parses `ffmpeg -list_devices`.
- Bounded by construction: the reader keeps **only the newest frame** (a buffer of one) and counts what
  it drops (C2); frames are sampled to RGB at the sampling rate inside the subprocess, so the pipe never
  carries more than the pipeline can take.
- Lifecycle: start, stop (the subprocess is stopped and reaped on every exit path, including the
  application's), the camera in use by another program (`CAMERA_IN_USE`), the device unplugged, and
  **reconnect with backoff up to a timeout, then close the session** (C7). A frame gap closes the open
  track: no continuity across it.
- Tests (CI, no camera): the fake emits rawvideo frames on a schedule; the real FFmpeg replays a
  generated clip through the identical pipe parser in the Windows CI job that M6 step 3 sets up. Killing
  the process mid-stream, a stalled consumer, a stalled producer, a corrupt frame size.
- Tracker: TST-071, TST-072.

### Step 3. The live class in the worker lease

- Add a `live` service class between interactive and background in `WorkerLease` (C6): interactive,
  then live, then background; the fairness rule generalises so a waiting background request goes first
  after the burst of grants to the two higher classes, which keeps a movie moving while a camera runs.
- A session has **at most one inference request outstanding**; the frame source drops newer frames
  while one is in flight, so the live queue is never longer than one.
- Tests: with a movie running in the background and searches arriving, the camera's wait is bounded and
  the movie still progresses; the lease is released in `finally`; cancellation and shutdown at
  boundaries. The per-class wait and execution times logged by M6 step 2 give p50 and p95.
- Tracker: TST-072, TST-077 (the contention half).

### Step 4. The live pipeline and encounters

- Detect on the sampled frame, track with M6's NumPy tracker, select observations with M6's selection,
  recognise at the per-face point on each selected observation with agreement (D7), and manage
  encounters: a track not seen for the encounter gap (C8) closes its encounter.
- **Persistence per closed encounter, atomically** (C3): the selected face snapshots (crops, at most
  three per track), their observations and representations, one `TRACK` occurrence with UTC start and
  end, and the evidence, in one transaction through the existing acceptance validation. Nothing from an
  open encounter is visible; a crash discards it (the partial output stays private, as in M3). An
  unmatched person is an unresolved occurrence in the review list, never a new identity (C5). Frames are
  never written.
- Recovery: startup marks a `RUNNING` camera run `INTERRUPTED` (existing recovery); no session is
  restarted automatically (C4).
- Tests: planted perception as in M3 and M6 (no models in CI), a camera session killed at each stage in
  a real child process, restart, and the same identity memory as before the session plus only the closed
  encounters: no duplicate occurrence, no lost evidence, human decisions intact.
- Tracker: TST-071, TST-072, TST-076 (the live half).

### Step 5. Camera screen, history and deletion

- Desktop: a Cameras screen (choose a camera, start and stop, status: running, frames dropped,
  reconnecting), a **"Camera on" indicator visible on every screen while a session runs** (C4), a live
  preview that is the newest annotated frame fetched from a loopback route and held only in memory
  (C3), and the history: encounters by camera and day, each with its snapshots.
- Deletion (spec section 9): one encounter, a selection, a day or range, all history of one camera, each
  with a confirmation; permanent through the M5 erasure path, with no Recycle bin (C9), leaving the
  audit trail detached as M5 step 4b does. Removing the camera configuration deletes nothing unless
  asked.
- Tests: route and use-case tests, byte-level checks that deleted snapshots are gone (as
  `test_permanent_source_delete.py` does), frontend tests, and a desktop end-to-end test using the
  scripted frame source.
- Tracker: TST-071 (history), SEC-006 (deletion privacy, the camera half).

### Step 6. Search with the camera (spec 10.4)

- "Search with camera": one frame captured, run through the existing face-search route and use case,
  and shown with the ranked possible matches. **Nothing is persisted, and the frame is not kept** (query
  is not ingest). It takes the interactive class, so it also works while a session is running.
- Tracker: TST-057A regression (face search unchanged), TST-071.

### Step 7. Runtime validation and benchmarks (TST-073 to TST-077), then the real-world check

- A reproducible benchmark script (the evaluation folder's conventions: Git-ignored output, a written
  JSON report): detect and embed latency on CPU, DirectML and, for the developer, CUDA, and a **ten
  minute soak** of the live pipeline (frames dropped, wait p50 and p95, memory growth, USearch growth).
- TST-073 (CUDA): closed on the developer-only verification of 2026-10-15 re-run inside the benchmark;
  CUDA is not a release gate (decision 2026-10-15). TST-074 (DirectML): validated on this NVIDIA machine
  only; AMD, Intel and no-DirectX-12 machines stay unverified and the row says so. TST-075 (CPU
  fallback): a forced DirectML failure falls back to the CPU visibly, **including during a live
  session**. TST-076: a provider change does not change the representation space; the recorded
  agreement (embeddings within 1.25e-6 between DirectML and CPU, 2026-10-16) is re-asserted by a test
  and a calibrated policy stays bound to its space. TST-077: the baselines are recorded for this laptop.
- **Real-world check:** the owner's own webcam for a few minutes (D8's rule: local and Git-ignored, no
  frames or snapshots committed): a session, a visit by the owner, a visit by someone unknown, a
  disconnect and a reconnect, a crash and the recovery. If the machine has no camera it stays open and
  is said so.
- Tracker: TST-073 to TST-077.

## 5. API surface (proposed in step 1; nothing here is spec until that PR is reviewed)

Under `/api/v1`, following the existing conventions (one error shape, cursor pagination, library
gating): `GET /cameras/devices` (what the computer offers), `POST /cameras` (configure one: a `CAMERA`
source), `GET /cameras`, `GET /cameras/{id}`, `DELETE /cameras/{id}` (removes the configuration only),
`POST /cameras/{id}/start`, `POST /cameras/{id}/stop`, `GET /cameras/{id}/status`,
`GET /cameras/{id}/preview` (the newest annotated frame, in memory), `POST /cameras/{id}/search`
(step 6), history through the existing occurrence reads filtered by source and time, and the deletion
routes of step 5. Events: `camera.session.updated` and `camera.encounter.closed`, best effort, as the
spec says events are notifications. Errors: `CAMERA_BUSY` (another session is running),
`CAMERA_IN_USE`, `CAMERA_NOT_FOUND`, `CAMERA_ACCESS_DENIED`, `CAMERA_DISCONNECTED`.

## 6. Dependencies, tracker IDs and definition of done

- **Depends on:** M6 step 2 (lease, one worker), step 3 (the pinned FFmpeg runtime and its CI
  arrangement), step 5 (tracker and selection) and step 6 (track-level recognition). Step 1 (spec,
  schema) can start once M6 step 3 has merged; steps 2 and 3 can be developed in parallel with M6 steps
  5 and 6 where they touch different files. If M6's tracker or selection changes shape, steps 4 and 6
  are re-read before they start.
- **Tracker IDs:** TST-071 to TST-077, SEC-006 (the camera half), SEC-005 (no network).
- **Done when:** TST-071 to TST-077 are `PASSING` with the evidence their rows ask for (TST-073 and
  TST-074 as scoped in step 7), the real-world check is recorded, a session killed at each stage and
  recovered leaves identity memory as it was plus only closed encounters, deleting camera history leaves
  no snapshot bytes behind, a soak shows a bounded backlog, and the milestone gate holds.

## 7. Risks

- **Privacy of bystanders.** Recording people who did not choose it is legally and ethically different
  from importing one's own photographs. Personal use at home is what this plan serves; a release to
  anyone else needs the biometric-privacy review that `licensing-and-commercialization.md` section 9
  lists. The defaults and C4 are the mitigation, not a solution.
- **CPU-only machines.** About 0.7 s per picture on the CPU (measured 2026-10-15) means about 1.4 frames
  per second; the drop policy keeps latency bounded, but recognition is slow. DirectML is about 0.03 s
  on this machine's NVIDIA GPU. The benchmark states what each machine can sustain.
- **DirectShow naming and exclusivity.** Device names are not stable identifiers across drivers, and a
  camera another program holds cannot be opened. Mitigation: show the device list on every start, map
  failures to the errors in section 5.
- **Identity drift.** Automatic evidence from an unattended camera can poison a person's memory. The
  mitigations are agreement across selected observations (D7), at most three admitted observations per
  encounter, no automatic identity, and the review list.
- **Lease starvation, both ways.** A camera running for hours can slow a movie to a crawl, and a movie
  can delay the camera. The burst rule bounds both; the soak measures it.
- **Long-lived process hygiene.** Subprocess leaks, handle leaks and memory growth over hours.
  Mitigation: stop and reap on every exit path, the soak test, bounded buffers everywhere.
- **Clock and time zones.** Encounters carry UTC wall-clock times; a clock change during a session can
  reorder them. Monotonic time orders frames inside a session; UTC is only recorded.

## 8. Decisions (delegated, 2026-11-09)

> **Decision 2026-11-09 (delegated decisions by the agent):** the owner delegated the remaining product
> and design decisions ("i'll leave the rest of the decisions entirely to you"). C1 to C12 are the
> agent's decisions, each with its reasoning and what reversing it costs. They are recorded in
> [the implementation entry](../implementations/2026-11-09-m7-plan.md).

| # | Question | Decision and reasoning (delegated) |
|---|---|---|
| C1 | Capture API within the locked stack | **The pinned LGPL `ffmpeg` (recommended for M6 by the D2 record, section 4.1) run as a subprocess: `-f dshow` for the device, raw video on a pipe.** It adds no dependency and no second runtime, keeps frames inside the backend process tree (nothing passes through the web view, so no WebView2 camera permission and no frame reaches the front end except the preview), and reuses the pipe parsing M6 needs. Rejected: browser `getUserMedia` (frames would cross into the web view and back; permissions and CSP change), OpenCV `VideoCapture` (not a baseline; "not the canonical media architecture", tech-stack section 6), a Rust camera crate in the shell (a second capture stack and a new dependency). Reversal cost: replace one adapter behind the frame-source port. That the pinned build has the DirectShow input is checked in the D2 record |
| C2 | Frame rate and the camera set | **Detection at up to 5 frames per second, configurable (`camera.sample_fps`), by sampling in the FFmpeg subprocess; a buffer of one frame, newest wins, drops counted; one running session at a time.** 5 fps gives several samples of a person crossing a doorway in about a second; the offline default of 2 fps (D4) would give two. A slower machine drops frames by itself, so latency stays bounded without a separate adaptive rule. One session at a time because there is one worker (C6); a second start answers `CAMERA_BUSY`. **Local devices only: no RTSP or network cameras** (they need stored credentials and a network connection, which the offline rule and #174 exclude; the specs say "configured camera" and "Laptop Webcam"). Reversal: network cameras are a later add-on to the same port |
| C3 | What is persisted from a live stream | **Persisted:** per closed encounter, one `TRACK` occurrence (source, identity or unresolved, UTC start and end) and at most **3** selected face snapshots (face crops only, as managed artifacts) with their observations, representations and evidence. **Not persisted:** frames, video, per-frame detections, the boxes of every track step, the preview (held in memory and replaced). This is the spec's default (encounter history and selected snapshots on, recording off) and the identity model's "not every frame is a learning event". An encounter is an `Occurrence` of kind `TRACK`, so no `encounter`, `appearance` or `track` tables are added (the same choice M6 makes for movies). Persistence is atomic per closed encounter, so a crash loses at most the open ones. Reversal: add the ERD's tables later; occurrences map onto them |
| C4 | Privacy defaults | **No camera starts on its own:** not at launch, not after a restart, not after a crash (the previous session shows as interrupted and the owner starts a new one; spec section 25's "a new session begins" is read as a new session the user starts). **A "Camera on" indicator on every screen while a session runs.** No recording exists to turn on (not built: the spec says "future settings"). No automatic deletion (spec). Frames never leave the process except the in-memory preview over the loopback API with the launch token. The indicator is the one addition not in the specs: it costs a few lines and is the visible counterpart of "off by default". Reversal: remove the indicator |
| C5 | Does a camera create identities? | **No.** An unmatched person becomes an unresolved occurrence in the review list, like an abstained face from an image. This follows the 2026-10-08 owner decision over the product spec's older 6.1. Matches are accepted under the per-face 0.45 / margin 0.10 point on each selected observation with agreement (D7); at most 3 observations per encounter are admitted to memory, and only from encounters whose observations agree. Reversal needs the owner's decision about automatic new identities as a whole, not a camera decision |
| C6 | Sharing the one worker with the M6 lease | **A third class, `live`, between interactive and background:** order interactive, then live, then background (movies, imports, indexing). The burst rule generalises: after 3 consecutive grants to interactive or live, a waiting background request goes first, so a movie keeps moving under a camera. A session has one request in flight, so the live queue is at most one. A face search made with the camera (step 6) is interactive. The starting value of 3 is D5's and changes only on benchmark evidence (step 7). Reversal: change the class order in one place |
| C7 | Reconnect | **Retry with backoff for 30 seconds (configurable: `camera.reconnect_timeout_seconds`), then close the session as disconnected.** The specs leave the "camera reconnect timeout" unset. A gap closes every open track; a reconnected stream starts new tracks (no continuity across unobserved time). Reversal: a setting |
| C8 | When does an encounter close | **After 5 seconds without a matching track (configurable: `camera.encounter_gap_seconds`), or when the session ends.** The specs leave it to implementation. Short enough that a person walking out and back is two encounters only after a real absence, long enough that a brief occlusion is not. To be tuned on the real-world check |
| C9 | Deleting camera history | **Permanent, immediate, with a confirmation, through the M5 erasure path (representations erased, snapshot bytes removed, audit detached); no Recycle bin.** The Recycle bin exists for media the user imported; snapshots of people from a camera are biometric and the spec asks for deletion, not for undo. Removing a camera configuration deletes no history unless the user also chooses to. Reversal: route deletions through the bin first |
| C10 | Camera face search (spec 10.4) | **In scope, as step 6:** one captured frame through the existing face search, nothing stored. It is a requirement of the specs and reuses a built route |
| C11 | The runtime rows TST-073 to TST-077 | **CUDA (073) is developer-only evidence, not a gate; DirectML (074) is validated on this machine only and says so; CPU fallback (075) is tested including mid-session; compatibility (076) re-asserts the recorded embedding agreement; benchmarks (077) are a reproducible script and a recorded baseline.** They follow decision 2026-10-15 (CUDA never shipped). The owner has one machine; verifying other vendors' GPUs is not possible and is not claimed |
| C12 | Testing without a camera | **A frame-source port with a scripted fake and a real-FFmpeg replay of a generated clip through the same pipe parser (Windows CI job); planted perception for the pipeline; process kills in real child processes.** The only test that needs a camera is the owner's real-world check in step 7, run locally, never in CI, never committed |

## 9. Open questions this plan leaves

1. **Network cameras (RTSP):** excluded by C2; say so if a camera of that kind is wanted.
2. **Whether the "Camera on" indicator is wanted** (C4); it is the one visible addition beyond the specs.
3. **Real-world check:** needs the owner's webcam and a few minutes; it stays open if the machine has no
   camera.
4. **C8's 5 seconds and C2's 5 frames per second** are starting values, tuned on the real-world check
   and the benchmark.
5. **Automatic new identities** stay off everywhere (C5); turning them on is a decision for all
   sources, not for cameras alone.

## 10. Not in this plan

Continuous recording or clip export (the specs say "future settings"), network and IP cameras, more
than one running camera, a second specialised worker, cross-camera tracking (the roadmap lists
"cross-camera behavior" later), natural-language camera queries, learned decision models, automatic
merges, retraining, and packaging (M8).
