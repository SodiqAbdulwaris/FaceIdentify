# A video track holds one person (issue #283)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M6 steps 5 and 6 (D6, D7); TST-063, TST-069; GitHub issue #283
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(video): a track holds one person, not whoever stands in its place`, `docs: record the one-person track decision for issue 283`

Numbers only. No file name, title, frame, face or name of a person from the owner's videos is
recorded in Git, a PR or CI; the videos were read in place, read only, and every library, cache and
script for the measurement lived in a scratch folder outside the repository, deleted at the end.

## Why

Issue #283: the tracker (`backend/app/processing/tracking.py`, NumPy only, D6) linked detections by
box overlap weighed by landmark-shape agreement. A cut to another face in the same place and pose
continued the track. Selection keeps up to `keep_per_track` (3) faces per track and chunk by merit,
spread by a minimum distance (not by coverage of the track's time), within a lifetime budget
`max_per_track` (12). So the kept faces could all be the first person's, and once the budget was
spent (about 40 s) nothing more was kept at all. The track rule (D7: every kept face must agree)
then passed and the whole span became the first person's appearance, while the second person's
faces were never recorded.

## What changed

- **`tracking.py`**: `Tracker.update` takes each box's unit embedding (`faces`, optional). A face
  joins a live track only if its cosine with the track's face is at least `SAME_PERSON` (0.2), on
  top of the overlap and landmark fit; otherwise it may join another live track or starts its own.
  The track's face is the last one it was given; `Tracker.recall` sets it, at the start of each
  chunk, to the track's most recent kept face. The faces are never part of `state()`.
- **`execute_job.py`** (`_chunk_work`, `_video_chunk`): every detected face of a chunk is embedded
  (in the same batched worker turns), then tracked with its embedding, then selected; only the kept
  faces are recorded, from the vectors already computed (there is no second embedding pass). The
  references (each track's most recent kept face) are brought up to date after the chunk is
  settled, so a chunk redone after a provider fallback starts from the same faces.
- **`video_chunks.py`**: `kept_faces(session, run)` reads each track's most recent kept face back
  from the run's chunk checkpoints and the stored representations, for a resumed run.
- **Not changed:** the checkpoint payload (positions and ids only), `keep_per_track`,
  `max_per_track`, `select_kept`, the track rule D7, and the camera pipeline (it calls the tracker
  without faces, so it links by position exactly as before; a camera has no cuts).

## Measurement, before the change

Two consecutive episodes of one series (MP4, HEVC, 720p, about 42 minutes each) and, because the
D8 film is no longer in the owner's folder, the longest file there: an hour-long episode of another
series (MKV, H.264, 720p), with no person in common with the first. Real `buffalo_l` models on
DirectML, scratch roots.

**How "two people" was decided.** A scratch script ran the product's own detector and embedder code
on every sampled frame and embedded **every** detected face (10,660, 5,389 and 7,936 faces in 5,066, 5,061 and 7,148 sampled frames), then
replayed the product's tracker and selection chunk by chunk. For each track, its faces were grouped
by single linkage at cosine 0.45 (the approved policy's match threshold: the app itself takes such
faces for the same person). A track **holds two people** when two groups of at least two faces each
have no cross pair above 0.20. For `buffalo_l`, different people sit near 0 and the same person,
turned or blurred, nearly always has some pair above that across several faces. **D7 is blind** to
such a track when its kept faces include faces of only one of the two groups: if that person is
named, the whole track is settled as one appearance. The replay's counts of today's code are exact:
the real app on the same episode kept the same 8,537 faces in the same 5,005 tracks.

| (today's code) | Episode 1 | Episode 2 | Other series |
|---|---|---|---|
| Tracks that kept a face | 5,005 | 1,808 | 2,783 |
| Multi-face tracks | 1,945 | 990 | 1,228 |
| Tracks holding two people | 53 | 29 | 29 |
| ...of which D7 is blind to (settled as one appearance if that person is named) | **7** | **4** | **7** |
| ...of which the second person comes after the budget is spent | 0 | 0 | 0 |

**A shot-change signal from pixels does not separate the change points.** Between the two faces of
a track where the person changes (60 such links in episode 1) and links where the same person
continues (4,629), with thresholds set at the continuation links' 99th and 99.9th percentiles (to
split 1 in 100 or 1 in 1,000 tracks for nothing):

| Signal between the two faces' frames | Change points caught at p99 | at p99.9 |
|---|---|---|
| Whole-frame luminance histogram (32 bins, every 8th pixel; total variation; median 0.045 over all frames, 0.25 at change points) | **41 of 60** (threshold 0.207) | 11 of 60 (0.362) |
| Luminance histogram of the face box | 5 of 60 (0.583) | 0 of 60 |
| Histogram of the face box doubled | 17 of 60 (0.395) | 2 of 60 |
| 8 x 8 block layout of the frame (mean absolute difference) | 36 of 60 (0.089) | 21 of 60 (0.133) |

Cuts inside one scene (dialogue framed alike) change the picture too little. Simulated over the three
files, tracks D7 is blind to (today: 7, 4 and 7):

| Candidate (simulated on the same detections) | Episode 1 | Episode 2 | Other series |
|---|---|---|---|
| (a) spread the kept faces over each track's time in the chunk (best face per equal time window) | 3 | 1 | 2 |
| (b) end every live track when the frame histogram changes by more than 0.207 | 1 | 3 | 7 |
| (a) and (b) together | 1 | 1 | 2 |
| (b) with the block layout above 0.09 instead | 2 | 1 | 7 |
| **A face joins a track only if its embedding is at least 0.2 alike with the track's face (built)** | **0** | **0** | **0** |

## The choice, and why

The orchestrator's options were (a) cover each track's time when selecting, (b) end live tracks at a
shot change from a compact frame signature, and (c) change D7 (an owner decision, out of scope).
Measured: (a) and (b), alone or together, leave tracks D7 cannot see (4 in all at best), and (b)
needs a pixel threshold that the data does not support; (b) would also put a frame signature in the
checkpoint. Embedding is the only signal that tells two people apart, and D6 already
names it ("IoU, landmarks, embedding when available"). The cost is embedding the faces that
selection did not keep before (it kept 8,537 of 10,660 in episode 1, 3,745 of 5,389 and 5,281 of
7,936 in the others), with no new model, dependency or threshold on pixels; it costs 5 to 8% of
throughput on DirectML and 12% on the CPU (below). A false split only splits a track (a person's appearance in two parts); a
missed change is today's behaviour, so the bound is set low (0.2).

**Resumability without vectors in the checkpoint.** The checkpoint payload stays "positions and ids
only" (persistence spec, decision of 2026-11-10): a vector in a checkpoint would outlive an erasure
of that face (only representation rows are erased). Each chunk therefore starts by comparing a
track with its most recent **kept** face, which is a stored, erasable representation: kept in memory
by a run that goes on, read back by `kept_faces` on a resume. Both compare against the same vector,
so a resumed run makes the same choice (a test kills a run inside the chunk where the second person
appears and checks the result). A face erased while a run is paused is not known on resume: that
track's next face is linked by position alone, as before this change.

## Measurement, after the change

The same replay with the product's new code:

| | Episode 1 | Episode 2 | Other series |
|---|---|---|---|
| Tracks holding two people (before: 53, 29, 29) | 2 | 0 | 0 |
| ...D7 blind to (before: 7, 4, 7) | **0** | **0** | **0** |
| Tracks that kept a face (before: 5,005, 1,808, 2,783) | 5,332 (+6.5%) | 1,887 (+4.4%) | 2,925 (+5.1%) |
| Kept faces (before: 8,537, 3,745, 5,281) | 8,732 (+2.3%) | 3,864 (+3.2%) | 5,396 (+2.2%) |

**Through the real app** (the backend in-process over its HTTP API, real models, DirectML first, a
fresh scratch library each side): episode 1 processed, six people named in it (every unresolved face
within cosine 0.6 of one of six reference faces taken beforehand from the cached embeddings: the four
largest groups that recur in episode 2 and episode 1's two largest that do not, as in D8), then
episode 2 and the other series' episode.

| | Before | After |
|---|---|---|
| Faces named in episode 1 (six people) | 1,092 | 1,133 |
| Named people recognised in episode 2 | 4 of 6 | 4 of 6 (the same four) |
| Matched faces in episode 2 | 1,675 | 1,863 (+11%) |
| Appearances (track occurrences) in episode 2 | 754 | 828 |
| Matched faces less than 0.3 alike with their person's reference (possible wrong merges) | 0 | 0 |
| Least alike matched face, per person (episode 2) | 0.39 to 0.42 | 0.39 to 0.42 |
| False matches in the other series (5,281 / 5,396 kept faces) | 0 | 0 |

Recall moved up, not down: matches withheld before by a mixed track, or hidden in another person's
track, are now their own tracks. The people are not D8's (their faces were chosen by the script,
not by eye), so "4 of 6" here is this sample's count, compared before against after.

**Throughput** (whole video path, video seconds per second):

| Run (fresh scratch library each) | Before | After | Change |
|---|---|---|---|
| Episode 1, DirectML, first pair (inside the recall runs above) | 8.36 | 7.91 | -5% |
| Episode 1, DirectML, second pair (alone) | 8.15 | 7.64 | -6% |
| Episode 2, DirectML (inside the recall runs) | 8.95 | 8.89 | -1% |
| Other series' episode, DirectML (alone) | 10.4 | 9.57 | -8% |
| Episode 1, CPU only (alone) | 3.13 | 2.74 | -12% |

The other series' episode inside the recall runs gave 4.84 before and 8.98 after; the "before" run was
slowed by something else on the machine (it is the outlier against the paired 10.4) and is left out.
The CPU is bound by inference (about 51 ms a face, the throughput entry of 2026-11-13), so embedding
every face costs it most. These episodes run slower than the 10.1 of the 2026-11-13 measurement,
which was another episode with fewer faces; each pair here is the same file before and after.

## Decision (delegated, 2026-11-14; the owner may reverse it)

> **Decision 2026-11-14 (agent, delegated by the owner on 2026-11-09; issue #283; reversible):** a
> video track holds one person. Every detected face of a chunk is embedded before tracking, and a
> face joins a track only if its cosine with the track's face (the previous face in the chunk, or
> at a chunk start the track's most recent kept face) is at least 0.2. Only the kept faces are
> recorded; `keep_per_track` and `max_per_track` are unchanged; the checkpoint holds no vector. To
> reverse it, call `Tracker.update` without `faces` and embed only the kept faces again (the code
> before this PR).

Proposed spec text (added as a decision note under the persistence spec's checkpoint decision of
2026-11-10, delegated): "The tracker's state holds no face vector: at each chunk start a track is
compared with its most recent kept face, read back from the stored representations on a resume."

## Verification

- `tests/integration/test_video_shot_change.py` (new): a red face, then a cut to a smaller green
  face in the same place, then red again, on generated clips: (1) in one chunk where red outranks
  green, (2) after the track's lifetime budget is spent, (3) killed inside the chunk where green
  appears and resumed. Each checks that red's appearances never cover green's time, that red is
  still recognised before and after the cut, and that a green face is recorded. All three fail on
  `main` (red's appearance ran 0 to 3.52 s and 0 to 7.52 s over green's time) and pass here. The
  resume case fails if `kept_faces` returns nothing (checked by hand).
- `tests/unit/test_tracking.py`: another person in the same place starts a track; the same person
  turned stays; two people alternating in one place each keep their own track; `recall` gives a
  resumed tracker its face, the state is the same with or without faces, and without a recalled
  face the tracker falls back to position.
- The full backend gate (`uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run mypy --platform linux && uv run pytest -q --cov`): exit 0, ruff and both mypy runs clean, **3,754 passed**, 4 deselected, coverage **100%** (`--cov-fail-under=100`), 43 min on this machine.

## Open issues / follow-ups

- **A track that ends inside a chunk gets its full budget back for that chunk's selection**
  (`Tracker.update` prunes the count of a track that is no longer live before `room` is asked), so it
  may keep up to `keep_per_track` more faces than `max_per_track` once. Pre-existing and small; seen
  while testing the resume case. Not changed here.
- The two remaining two-person tracks in episode 1 are ones D7 already withholds (both people among
  the kept faces).
- `SAME_PERSON` is a cosine of `buffalo_l`'s space; another model would need its own measurement.
