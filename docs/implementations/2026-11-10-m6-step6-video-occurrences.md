# M6 step 6: track-level recognition and occurrences over time

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 6; D7; TST-061, TST-063 (segments), TST-070 (part)
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(processing): settle video tracks and record occurrences`,
  `docs: record M6 step 6`

## What changed

- `backend/app/recognition/reasoner.py`: a new abstention reason, `TRACK_UNSETTLED`, which the reasoner itself
  never gives.
- `backend/app/processing/video_chunks.py`: `agreed_identity`, the track rule (D7) shared by the executor and
  acceptance: a track is placed only when every kept face's own decision, at the per-face operating point
  (0.45 / margin 0.10 in the real policy), is a match to the SAME identity.
- `ExecuteProcessingJob` (video): after recognition, the faces of every other track become abstentions with
  reason `TRACK_UNSETTLED` and their own proposal kept in the evidence (`proposal`: outcome, reason,
  identity). So a video never creates an identity automatically (a would-be new identity is unsettled).
- `AcceptProcessingRunUseCase`: FINAL may carry `tracks` (only for a video Source, and every observation in
  exactly one track); each face is validated against its own evidence as before (an unsettled face's
  recorded proposal must be what its evidence decides); then the track rule is checked on those
  re-derived decisions (a settled track has no unsettled face; an unsettled one has only unsettled faces).
  A settled track becomes ONE `TRACK` occurrence with its start and end time and frame, its matched faces as
  members; an unsettled track's faces are accepted as abstentions (findable, identity-less, with
  `RECOGNITION_ABSTAINED` evidence) and make no occurrence. A second acceptance validates the stored track
  occurrence. A video Source is acceptable (it was image-only).
- API: an occurrence summary has `start_ms` and `end_ms` (None for an image); OpenAPI and TS types regenerated.
- Tests: `tests/integration/test_video_occurrences.py` (an enrolled identity, then a clip whose red track
  settles into one occurrence 0 to 2520 ms with several members and whose green track abstains with its
  proposals; idempotent re-acceptance and a missing member found; eleven tampered FINALs refused; an image face
  left unsettled refused).

## Why

M6 step 6 (Roadmap section 69: "Person X appears 00:04:21 to 00:04:47"), under D7: reuse the per-face point on
each selected observation and require them to agree.

## Decisions

Delegated (owner, 2026-11-09; reversible):

1. **Agreement means all kept faces MATCH the same identity.** One abstaining face, one would-be new identity
   or two identities leave the whole track unsettled (conservative: ML is evidence, not truth).
2. **A video never creates an identity automatically**, even in an empty library (the image rule "only the
   first face of an empty library creates one" stays for images). Unknown tracks wait for the person, as
   abstentions.
3. **No automatic movie-local grouping of unknown tracks.** Grouping without an identity has nowhere to live
   in the identity model and would be an automatic decision of its own; the faces are findable for review.
   Revisit with the owner's videos (D8).
4. **One occurrence per settled track**, its representative the track's first matched face; the occurrence
   spans the track's whole time (every detection, not only the kept faces).
5. Spec text: persistence section 15 (the FINAL `tracks`) is extended by this note in the entry; the
   `TRACK_UNSETTLED` reason and the `proposal` evidence key are recorded in `PERSISTENCE_IMPLEMENTATION.md`
   section 11 (evidence).

## Verification

- `uv run pytest -q tests/integration/test_video_occurrences.py tests/integration/test_accept_processing_run.py
  tests/integration/test_execute_video_job.py tests/integration/test_reprocess_images.py
  tests/recovery/test_finalizing_recovery.py`: all pass. Full gate in the PR.
- `npm run generate:api`, `npm run typecheck`: clean.

## Open issues / follow-ups

- Reprocessing a video (carry-over through tracks) and video retry: step 7.
- The video screen showing appearances on a timeline: step 7.
