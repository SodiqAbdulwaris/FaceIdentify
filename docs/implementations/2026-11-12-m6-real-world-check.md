# M6 step 8: the real-world check on the owner's videos (D8)

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M6 step 8 (D8); TST-070
- **Status:** done; two defects found and fixed (PRs #252 and #254), one logging change here
- **Commits:** PR (number recorded when merged): `docs: record the M6 real-world check`, with
  `fix(api): log a failing processing loop by class name`

Numbers only. No file name, title, frame, face or name of a person from the videos is recorded in
Git, a PR or CI; the videos were read in place, read only, and every library, index, contact sheet
and model copy made for the check lived in a scratch folder outside the repository, deleted at the
end.

## The sample, and how it was chosen

Of the owner's 369 local videos (all probed and decoded by the pinned ffmpeg, see the step 4
entry), four were chosen:

- **Three consecutive episodes of one live-action series** (HEVC, 720p, MP4, about 2,466 s each).
  A recurring main cast makes "named in episode 1, recognised later" a real question.
- **One live-action feature film** (HEVC 10-bit, 1916 x 798, MKV, 5,821 s): the longest common
  case, another container and pixel format, and a cast that shares nobody with the series, so any
  match to the series' people would be a false one.

## How it ran

The real app path: the backend host (`python -m backend.api.host`) driven over its HTTP API, the
real `buffalo_l` models, the owner-approved automatic-matching policy (0.45 / margin 0.10, its bytes
copied into the scratch state; the live policy file was read, never written), a scratch library
and state root, one heavy job at a time. Other sessions were running test suites on the same
machine throughout, so every timing below is on a loaded machine and slower than it would be
alone.

**CPU, not DirectML, for the main runs:** the model package installed in the owner's live state
predates the DirectML variants (its manifest lists CUDA and the CPU), so the app runs on the CPU
there, with no fallback reported, because the CPU is what that package offers. A second scratch
state with the reference package (DirectML, CUDA and CPU variants) and a fresh library measured
DirectML on one episode.

## Results

| Measure | Result |
|---|---|
| Decoding | All four files decoded end to end by the pinned ffmpeg; no file refused |
| Throughput, CPU | 3.4 to 4.0 video seconds per second per run (2.4 once, under the heaviest load); the film 4.0 (5,821 s in 1,451 s) |
| Throughput, DirectML | 4.5 (episode 1, 545 s; the same 7,264 kept faces as on the CPU, no fallback). Barely faster than the CPU: decoding, sampling and tracking on the CPU are the bound, not inference |
| Peak memory (host + ML worker + ffmpeg) | About 1.0 GB, film included (largest single sample 1,055 MB, on DirectML) |
| Kept faces | Episode 1: 7,264 in 3,938 tracks; episode 2: 5,191; episode 3: 3,864; film: 5,819 in 3,047 tracks |

**Recognition across episodes.** Six recurring people were named from episode 1 (1,084 of its
faces, grouped by face similarity, checked by eye, then resolved and named through the API). With
both fixes in:

| | Episode 2 | Episode 3 |
|---|---|---|
| Named people recognised | 4 of 6 | 4 of 6 (the same four) |
| Track occurrences (appearances) | 187 | 85 |
| Matched faces | 390 of 5,191 | 169 of 3,864 |

Of the two not recognised, one is present in episode 2 (58 faces whose nearest named person is
them, similarity up to 0.80) but abstains as `AMBIGUOUS_CANDIDATES`: the nearest rival is usually an
unnamed face of episode 1, most of whose faces are not named. The other barely appears (10 faces,
best similarity 0.56).

**Wrong merges:** none confirmed. Every matched face of the most-matched person in episode 2 (91)
and in episode 3 (70) was checked by eye, and samples of the others; faces under very different
light or hair sit at similarity 0.72 to 0.78, far above what two different people reach with this
model. Four matched crops in those sets are not usable faces (hair, a blur through leaves, an eye
close-up, a dark frame) that rode in on a matched track.

**False matches:** none. Not one of the film's 5,819 faces matched any of the six series people.

**Splits:** a video never creates an identity, so the app cannot split anyone by itself. Recall is
the limit instead: most faces abstain, mainly as ambiguous or uncertain similarity under the
uncalibrated policy, and the track rule (D7) withholds a whole track when its faces do not all agree
(211 per-face matches in episode 2 were withheld that way). In episode 1, 277 of 1,845 multi-face
tracks held two people (a cut inside a track); D7 is what keeps those from becoming wrong matches.

## Step 7's controls on real files

| Control | Result |
|---|---|
| Pause, resume | Episode 2 paused at 1,260 of 4,933 slots within 4 s; resumed from that slot, finished, nothing redone |
| Cancel | Episode 3 cancelled at 1,000 of 4,930 slots within 1 s; processed again as a new run. A retry of a cancelled run is refused (`RUN_NOT_RETRYABLE`), as the retry contract says |
| Restart mid-job, retry | The host killed during episode 1's recognition: recovery marked the run `INTERRUPTED`, a retry resumed the same run as attempt 2 and completed (D10) |
| Reprocess | Episode 2 reprocessed after the fix; the new generation superseded the first |

## Defects found

1. **Recognising a video's faces was quadratic** (PR #252, merged). Each face asked the index for
   `k` plus every excluded face of the video and rebuilt a run-local index of excluded faces: more
   than 17 minutes unfinished for episode 1's 7,264 faces, then 13 to 37 s.
   [Entry](2026-11-12-video-recognition-retrieval.md).
2. **The index never caught up after a video** (PR #254, merged). After an acceptance the host
   applied one batch of 100 index operations and nothing else ran the queue; a video queues
   thousands, so every later recognition abstained as `RETRIEVAL_INCOMPLETE` and no one named in one
   video was ever recognised in the next (episode 2: 0 of 5,191 faces before the fix). The
   processing loop now drains what is due before each claim; 11,255 operations drained in about
   17 s. [Entry](2026-11-12-drain-index-after-acceptance.md).
3. **A failing processing loop left no trace** (this PR). It is now logged at warning level, by
   class name only. That is how the check saw the other loop's claim meet `DatabaseBusyError`
   during a big acceptance (harmless: it waits one interval and tries again).

## Seen, not fixed

- **One acceptance sat in `FINALIZING` for over 55 minutes** (episode 1, the heaviest load of the
  day). Not reproduced: recovery accepted the same run in 30.7 s on a copy, and later acceptances
  of 3,800 to 5,800 faces took seconds. Probably load; the logging above would now show a loop
  failing behind it.
- **The live package has no DirectML variant**, so the owner's app runs on the CPU. Moving needs a
  decision (a library refuses a different manifest for a package it registered; see
  `docs/guides/INSTALLING_MODELS_WINDOWS.md`).

## Verification

The runs above (scratch library, real models), the merged PRs' own tests and CI, and for this PR:
`uv run pytest -q tests/integration/test_api_scheduler.py` (8 passed, including the new check that
a loop failure is logged by class name without its message).
