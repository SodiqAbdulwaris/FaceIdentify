# M7 step 4: camera sessions and encounters

- **Date:** 2026-11-12 (work began 2026-11-11)
- **Milestone / tracker IDs:** M7 step 4 · TST-071 (sessions), TST-072 (the live class in use), TST-075 (fallback during a session), TST-076 (the live half: a session killed and recovered)
- **Status:** done (the backend pipeline; routes and screen in step 5)
- **Commits:** PR (number recorded when merged): `feat(cameras): track faces into encounters`, `feat(cameras): run a camera session and accept each encounter`, `fix(cameras): mark every unwritten crop when a write fails`, `docs: record M7 step 4`

## What changed

- `backend/app/cameras/encounters.py`: M6's NumPy tracker over the session's monotonic time (slots of `1 / sample_fps`); a track unseen for `encounter_gap_seconds` (5 s, C8) closes its encounter; a `Gap` closes all and starts a new tracker (no continuity across unobserved time). An open encounter keeps a small pool (8) of its best sightings by M6's merit, each as a **face crop** (the box plus half its size on every side) with the detection redrawn in the crop's coordinates; frames are never kept. At closing, M6's `select_kept` picks at most 3 (C3), spread over the encounter.
- `backend/app/cameras/session.py`: `start_camera_session` (one transaction: an active `CAMERA` Source, no other session running (`CameraBusyError`), the processing request resolved and frozen with the camera settings beside it, a `PROCESS_CAMERA_SESSION` job created and claimed at once, run `RUNNING`, first segment). `CameraSessionExecutor` (a subclass of the image and video executor, reusing its plan, fallback segments, decision and settlement helpers): each frame is detected in the worker's **live** class; each closed encounter's chosen sightings are embedded (live class), their crops written as managed `FACE_CROP` JPEGs, their observations and representations written as private `PENDING` output in one transaction, decided as a video's faces are and settled by the track rule D7, then accepted in one transaction by `accept_encounter`. A stop records the open encounters and completes segment, run and job; a camera that does not come back or a failing worker records what it can and ends the session `FAILED` with the reason's code.
- `backend/app/processing/accept_run.py`: `accept_encounter`, which accepts ONE closed encounter of a running camera run through the same validation as a FINAL checkpoint (the faces are exactly the run's private output, each decision follows its evidence, D7 holds) and the same effects as one video track (matched faces join their identity and become one `TRACK` occurrence from the encounter's first to its last UTC millisecond; an unknown person's faces become identity-less active representations with abstention evidence). `_context` accepts a camera run's job type; `_validate_private_output(pending_only=True)` compares only the still-private faces (earlier encounters are already accepted).
- `backend/app/processing/execute_job.py` (rebase onto main): a camera, like a video, builds no run-local index (an encounter's faces are all left out of each other's candidates).
- Tests: `tests/unit/test_camera_encounters.py`, `tests/integration/test_camera_session.py` (painted squares and scripted frames: a known person's visit is one occurrence accepted while the session runs; an unknown person creates nothing; two people at once; a gap; a stop with someone in view; a camera that does not come back; a worker failure; one session at a time; only an active camera; malformed settings; acceptance refusals; a provider fallback mid-session starts a new segment (TST-075); a crop that cannot be written), `tests/recovery/test_camera_process_kill.py` (a session in a real child process killed with a visit open, and after a visit's faces were written but not accepted: the run is `INTERRUPTED`, the first visit stays, the second leaves no appearance, nothing restarts, a new session records normally), fixtures `tests/fixtures/camera_pipeline.py` and `camera_child.py`.

## Why

[M7 plan](../plans/M7_PLAN.md) step 4, decisions C3 to C8; persistence 15 as amended in step 1 (each closed encounter accepted on its own while the session runs).

## Decisions

> **Decision 2026-11-12 (delegated decision, M7 step 4):** a camera face's observation box is relative to its stored crop (the crop is the face's picture: a camera has no original to cut it from), its `timestamp_ms` is UTC wall-clock milliseconds and its `frame_index` the frame's number in the stream. Encounter occurrences carry the same UTC times.

> **Decision 2026-11-12 (delegated decision, M7 step 4):** a camera never creates an identity (C5): each encounter is settled by the same track rule as a video (D7), so a face that would start a new identity abstains as `TRACK_UNSETTLED`, keeping its own proposal in its evidence.

> **Decision 2026-11-12 (delegated decision, M7 step 4):** an encounter keeps a pool of its 8 best sightings while open (bounded memory), and at most 3 are recorded (C3). A session's job is claimed with an effectively unbounded lease (one year): its claim lasts as long as the session, and startup recovery settles a crashed one.

> **Decision 2026-11-12 (delegated decision, M7 step 4, after the review):** a provider fallback while an encounter is embedded starts a new segment and the whole encounter is embedded again under the provider that now runs (as a video chunk is redone), so every face and vector names the segment that produced it; an encounter's times are when its frames arrived (the session's UTC start plus each frame's monotonic arrival), not when the worker got to them; a crop write that fails settles all of the encounter's reservations and removes any crop already written.

## Verification

Targeted (2026-11-12): the camera unit, integration and recovery tests pass (28 + 2); `encounters.py` and `session.py` 100% covered. The full backend gate is in the PR.

## Open issues / follow-ups

The encounter gap (5 s), the rate (5 fps) and the pool are starting values to tune on the real-world check (plan section 9, item 4).
