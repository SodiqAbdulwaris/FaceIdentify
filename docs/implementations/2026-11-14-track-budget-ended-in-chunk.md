# A track that ends inside a chunk keeps its budget for that chunk

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M6 step 5 (D6); TST-063; follow-up recorded in the issue #283 entry
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(video): a track ending in a chunk keeps its budget there`

## What changed

- `backend/app/processing/tracking.py`: `Tracker.update` no longer drops the kept-face count of a
  track when it ends. `Tracker.state()` leaves ended tracks' counts out instead, so the checkpoint
  is what it was (counts of live tracks only).
- `tests/unit/test_tracking.py`: a track whose lifetime budget is spent, continued into the next
  chunk and ended before that chunk's selection, has no room left. It failed before (room 7 of 7).

## Why

A video track may keep `max_per_track` (12) faces over its whole life. The count was dropped as
soon as the track was no longer live, which happens inside `update`, before the chunk's selection
asks `room`. A track that ended inside a chunk (more than `max_gap` slots before the chunk's last
frame) therefore got its full budget back for that chunk and could keep up to `keep_per_track` (3)
faces more than the limit, once. Recorded as a follow-up in
`2026-11-14-video-track-one-person.md`; the owner asked for the fix on 2026-11-14.

## Decisions

None. The limit is the one already decided (D6); the checkpoint payload is unchanged. Within a run
that goes on, the tracker now holds the counts of the tracks that ended in the current chunk until
the next checkpoint is taken from `state()`; a resumed run starts from the checkpoint, and an ended
track is never seen again, so both make the same choices.

## Verification

`uv run ruff format --check`, `uv run ruff check`, `uv run mypy`: clean. `tests/unit/test_tracking.py`,
`tests/integration/test_video_shot_change.py` and every test file that mentions a video or a track:
752 passed. Full gate and coverage (enforced at 100%): CI on the PR's head.

## Open issues / follow-ups

None.
