# Overnight run, 2026-10-15 night to 2026-10-16 morning

The unattended overnight run the owner set up on 2026-10-15 (instructions in the Git-ignored
`evaluation/datasets/reports/overnight-supervisor-prompt.md`): merge the queue, re-measure on
DirectML, close out M5, fix backlog issues, draft the M6 plan. This page says what was planned, what
happened, and what waits for the owner.

## How it ran (and why it differs from the plan)

- **No side sessions.** The plan was a supervisor dispatching Sonnet and Haiku sessions. The app
  refuses to start sessions from a turn that another session began ("start sessions only on the
  user's own words"), so the supervisor did the work itself, one item at a time in its own
  worktrees, with the same rules (Conventional Commits, docs with every change, full gates, an
  independent Codex read-only review on every PR, answered before merging).
- **A usage-limit stop** of about seven hours (from roughly 01:45 to 08:40) ended the night's work
  early. Nothing new was started after the 07:00 cut-off; the in-flight PRs were finished in the
  morning.
- **Merge rule** (owner, 2026-10-15): merged only with an answered independent review and green CI on
  the exact head; anything touching `docs/specs/`, a dependency, a threshold, policy or model, or
  deleting data would have been left for the owner. **No PR tonight fell under those exceptions.**

## Merged

| PR | What |
|---|---|
| [#204](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/204) | LFW Kaggle mirror licence field recorded (queue) |
| [#205](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/205) | Gate reports list exclusions by rule, with the cascade (closes #182) (queue) |
| [#206](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/206) | MyFaces close-ups (#173) and the finished CelebA run (queue; rebased by the supervisor) |
| [#207](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/207) | Weights' provenance re-checked and a Windows install guide (closes #69) |
| [#208](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/208) | M6 movies and scheduling plan, **draft** (ten open decisions, below) |
| [#209](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/209) | M5 definition-of-done audit: coverage 100%, M5 not done yet, what closes it |
| [#211](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/211) | DirectML re-measure: identical results to the CPU, about 3.5 times faster |
| [#210](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/210) | A missing original comes back: rechecked on open, process and retry; Recheck file and Locate original (closes #179) |
| [#214](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/214) | M5 tracker caught up from re-run suites (TST-058, SEC-006, TST-059 4a/4b passing; TST-054 needs an end-to-end correction test) |
| [#217](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/217) | Test fix: a `database is locked` flake from #210's retry test; `finished()` now waits for the index pass |
| this PR | This report, and a correction to PR 207's note on the policy backup |

## Open, and why

| PR | Why it is open |
|---|---|
| [#212](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/212) (#174, face-search paths that lead to a share) | The review found four P1 bypasses, not fixed tonight: `\\?\C:\NUL` normalising to a device, reparse points other than symlinks and junctions, `subst` drives hiding components, and the check-to-open race; plus tests that cannot show no outbound access. Not ready |
| [#213](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/213) (#175, face search before background work) | The review found a P1: one lease per plan rather than one boundary for the single worker, so two plans run two queues; and an interrupted wait can leave the queue stuck. Not ready |

## Results worth knowing

- **DirectML matches the CPU** (PR 211): the conservative operating point is identical on all 686
  photographs of the 48-identity verified set (embeddings within 1.25e-6), and the hard-negative gate
  gives identical metrics, workflow checks, stranger results and top-1 answers for all 267 queries,
  in about 36 minutes against 2 h 8 min on the CPU. The 0.45 / 0.10 point stands on DirectML.
- **Backend coverage is 100%** on main (3,081 tests at the audit; 3,105 on PR 210's branch).
- **M5 is not done yet** (PR 209's audit): with PR 214 the tracker catches up; what is left is
  TST-054's end-to-end correction test, the owner's decision on TST-038/039's local-only evidence,
  a review of TST-044 against the verified operating point and the DirectML re-measure,
  and a real-model check of automatic acceptance under the installed policy (TST-057B).
- **The live policy:** installed by the owner at 23:58 (`buffalo-l-verified-match-v1`), with the
  abstain-only restore copy rewritten at 23:59. (PR 207's entry, written at 23:58, says the backup
  held the matching policy; that was briefly true and is corrected by this report's PR.)

## Decisions taken overnight (delegated; please confirm or overturn)

> **Decision 2026-10-16:** (delegated by the owner overnight, pending confirmation) #174 is built as
> the locked policy's default (deny every network target, since no root can be approved yet) rather
> than with the approved-roots opt-in, which needs its own configuration and screen.

> **Decision 2026-10-16:** (delegated by the owner overnight, pending confirmation) #179: "opening" a
> source means its detail read, and "using" it means processing or retrying; the library listing
> never verifies (no library-wide scan). An original without a recorded fingerprint is never brought
> back by recheck.

> **Decision 2026-10-16:** (delegated by the owner overnight, pending confirmation) #175's fairness
> parameter is a constant 3 (three searches in a row at most before waiting background work) until a
> benchmark picks one.

> **Decision 2026-10-16:** (delegated by the owner overnight, pending confirmation) tracker rows
> TST-058, SEC-006 and TST-059 4a/4b marked `PASSING` from re-run suites; TST-054 left `IN_PROGRESS`
> because its criterion is an end-to-end test (PR 214).

- **#180 (reprocessing) was not built:** its locked decision defers it to M6; it is step 1 of the M6
  plan instead.
- **M6 plan, ten decisions (D1 to D10), each with a recommendation**, in `docs/plans/M6_PLAN.md`
  section 7: spec changes per step; FFmpeg and ffprobe as a pinned LGPL runtime package plus PyAV;
  the reprocessing face-correspondence rule (same representation space only); 2 fps sampling;
  fairness burst; NumPy-only tracker first; per-face acceptance on tracks; the owner's own test
  videos; reprocessing inside M6; video retry resumes from the last checkpoint.

## Not done

- **The automatic-acceptance workstream** the owner added at about midnight (check how automatic
  matches are shown, recorded and undone; a how-to for turning it on and off; a real-model check under
  the installed policy, then TST-057B): **not started** (it arrived mid-turn, then the usage limit).
  Recommended as the next task.
- #181 (label review: which face carries the label) and #66: not started.
- #174 and #175 are open with review findings to fix (above).

## Housekeeping

- Git-ignored data written tonight, all under `evaluation/datasets/`: `dml-state/` (a scratch state
  root with the same weights, for the re-measure), `gate-dml-hard-wide/` (the gate's library),
  `celebs-commons/cpu-cache-backup/` (the DirectML embedding cache), and the reports
  `*-dml.json`, `operating-point-dml-cached-invalid.json`, `dml-remeasure.log`. Nothing under
  `local-models/` was written. Delete them when no longer useful.
- Temporary worktrees `../FI-*` next to the checkout can be removed (`git worktree list`).
