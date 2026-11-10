# M6 step 7: pause, resume, retry, one movie at a time, video reprocessing and the video screen

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 7; D10; TST-060, TST-061 (video), TST-062, TST-064 (video), TST-065,
  TST-066, TST-067 (video), TST-068, TST-070 (part)
- **Status:** done, except the D8 real-world check (step 8, the orchestrator's) and a desktop end-to-end run
  with real video
- **Commits:** PR (number recorded when merged): `feat(processing): pause, resume, retry and admit video runs`,
  `test(processing): a retried run's newest job is its job`, `feat(processing): reprocess videos under the
  track rule`, `fix(api): show a resumed video run with its newest job`, `feat(processing): report a video
  run's progress in sampled slots`, `feat(frontend): show a video's appearances, progress and pause`,
  `test(recovery): kill a video run at each stage and recover it`, `docs: record M6 step 7`

## What changed

- **Pause and resume** (`backend/app/processing/pause.py`, `POST /jobs/{id}/pause` and `/resume`, API 13 to
  15): a running video run and its job become `PAUSING`; the executor finishes the chunk in hand (its
  checkpoint written), ends the segment and settles run and job `PAUSED`. Resume puts the job back in the
  queue (`QUEUED`, the run `PENDING`); the scheduler claims it as any job, a new segment starts, and the run
  continues after its last chunk (it keeps its first `started_at`). A repeat is harmless; a paused run can be
  cancelled (both `CANCELLED`); a crash while `PAUSING` is settled `PAUSED` by the existing recovery. Pending
  output may still be written while a run is `PAUSING` (the chunk in hand). `409 JOB_INVALID_TRANSITION` for
  anything else, including an image run.
- **Retry of a video run (D10, `RetryProcessingUseCase`):** a video run that stopped `INTERRUPTED` or `FAILED`
  with at least one chunk checkpoint, whose frozen snapshot can still be planned with what is installed
  (`snapshot_runnable`), is resumed: a new job (attempt + 1, `previous_job_id`) on the same run, the run back
  to `PENDING` (API 15). Otherwise it is a new run as for an image, the old run's private output untouched.
  A run therefore has one job or, after such a retry, more: `JobRepository.current_for_run` (the newest
  attempt) is what cancel, pause, acceptance and the run detail use.
- **One heavy movie at a time** (processing spec 8, API 16): the backend runs two scheduler loops, one claiming
  video jobs and one everything else, both sharing the one worker lease; the video loop never claims while a
  video run is `RUNNING`, `PAUSING`, `CANCELLING` or `FINALIZING` (a paused movie frees the slot).
- **Reprocessing a video** (step 1's rules on video): a face corresponds only to a face of the same sampled
  frame (`Face.time_ms`; same time and box IoU >= 0.7, then cosine >= 0.9 as D3); a carried-over human decision
  joins its track's occurrence; a track gets one occurrence per identity its placed faces (matched or carried)
  name. A lone carried video face outside any track would be a moment-long `TRACK` occurrence.
- **Progress:** each chunk records slots done of the whole video's slots on the job (API 17).
- **Frontend** (`SourcePage`, `VideoPanel.tsx`): a video source shows its length and size, who appears when
  (a row per person, bars along the video, the times written out, e.g. "4:21 to 4:47"), a progress bar with an
  estimate of the time left while it runs, and Pause, Resume and Cancel. The video itself is not downloaded to
  the page (movies are gigabytes). The desktop picker offers videos (`VIDEO_EXTENSIONS`, matching the backend).
- **Tests:** `tests/integration/test_execute_video_job.py` (pause at a chunk boundary and resume with every
  frame once; a pause after the last chunk; refusals; a pausing run whose job changed fails safely; the runner's
  `PAUSED` outcome; D10 resume of the same run with history kept and the fresh-run fallbacks; snapshot
  runnability; one movie at a time with an image beside it), `tests/integration/test_api_jobs.py` (the routes,
  cancel of a paused video, the newest job in the run detail), `tests/integration/test_video_occurrences.py`
  (a named track carried over on reprocessing), `tests/unit/test_correspondence.py` (frames), and
  `tests/recovery/test_video_process_kill.py`: a real child process running the video is killed mid-run, while
  pausing and after FINAL; the next start interrupts, pauses or accepts it, the retry or resume finishes it, and
  each ends with one appearance over the clip, no identity twice, no observation twice.
  `frontend/src/features/source/SourcePage.test.tsx` (the video page).

## Decisions

Delegated (owner, 2026-11-09; reversible). Spec text recorded as dated notes in `docs/specs/API and Contracts.md`
13 and `PERSISTENCE_IMPLEMENTATION.md` 16:

1. **Only video runs pause**, at chunk boundaries; a pause ends its segment `NORMAL` (the run says `PAUSED`; no
   schema change for a new end reason).
2. **D10 as above**; "still runnable" means the frozen snapshot plans with the installed packages.
3. **Two scheduler loops** rather than a heavier admission scheduler; the worker lease already arbitrates.
4. **No in-page video playback** in M6: the media route has no Range support and a movie cannot be held in
   memory; appearances are shown as times. Playback is a follow-up.
5. **Corrections on video faces** stay on the identity screens; the source screen lists people and times.

## Verification

- Targeted runs of every file above: all pass. Frontend: `npm run typecheck`, `SourcePage.test.tsx` 32 passed.
  Desktop: `cargo fmt --check`, `cargo test` 21 passed.
- Full backend gate on the stack (steps 5 to 7): see the PR.

## Open issues / follow-ups

- Step 8, the D8 real-world check on the owner's videos (the orchestrator's). The owner's library was already
  used read-only to make probe and decode robust (step 4 entry: all 369 files probe and decode).
- In-page playback with HTTP Range on the media route; a desktop end-to-end test with a video.
