# Progress: where FaceIdentify stands, and what is left

**Status:** implementation **paused by the owner on 2026-10-28**. This page is the snapshot to resume
from. It does not replace [`PROJECT_STATUS.md`](PROJECT_STATUS.md) (the one-page map) or
[`.agents/CONTEXT.md`](../../.agents/CONTEXT.md) (the agent's state and decisions): it says what was
in flight when work stopped and how to pick it up.

Snapshot taken on `main` at commit `44bf794` ("docs: reconcile the M5 note and D1 with the M6
approval").

## 1. Where the project stands

| Milestone | Status | Notes |
|---|---|---|
| M0 to M4 | Done | Domain, persistence, single-image ML, desktop shell and API |
| **M5** recognition and memory | **Done** | Declared complete by the owner on 2026-10-21 as of `main` `a778d81`, after a full-gate run (3,237 backend tests at 100% coverage, 206 frontend tests, both desktop end-to-end tests, the Tauri build and green CI). [Declaration entry](../implementations/2026-10-21-m5-complete.md), [audit](M5_DOD_AUDIT.md) |
| **M6** movies and scheduling | **In progress, paused** | [Plan](M6_PLAN.md) approved 2026-10-21 with decisions D1 to D12. No M6 code exists. Step 1's spec proposal is an open draft PR (section 2) |
| M7 cameras | Not started | No plan yet |
| M8 packaging and release | Not started | No plan yet; carries the release blockers in section 4 |

Automatic acceptance is live at the owner-approved operating point (0.45 / margin 0.10,
`buffalo-l-verified-match-v1`, installed 2026-10-15).

## 2. Work in flight when it paused

**Draft PR #229, `docs(specs): propose M6 step 1 reprocessing generations (issue 180)`**, branch
`feat/reprocess-images`. This is phase 1 of M6 step 1 (#180): spec text only, no code. Under D1, code
is written only after the owner approves this text.

- **Contents:** proposed edits to the persistence, identity-model, API, ERD and processing specs, each
  labelled "Proposed decision" so it becomes an owner decision on approval, plus a step plan
  `docs/plans/M6_STEP1_REPROCESS_PLAN.md` (on that branch only, not yet on `main`) (Alembic revision `0011`,
  use cases, and #180's seven acceptance tests mapped to TST-061, TST-064 and TST-067).
- **Review state:** a Codex read-only review of the spec text found five issues, all fixed in the
  PR's last commit. The reviewer was not re-run on that fix; re-review the exact head before anything
  else. All six CI checks were green on that head.
- **Its worktree and session are kept:** `.claude/worktrees/reprocess-images-fbcef7` and the Claude
  Code side session "M6 step 1: reprocessing images (#180)", which holds its context.

**The owner's decision needed to resume:** approve the spec text, and answer its eleven open
questions. The authoring session's recommendation is given for each; the full list is in the PR
description.

| # | Question | Recommendation |
|---|---|---|
| 1 | D3 says "one-to-one" with no tie-break | Mutual and unique pairs only; a face with two or more candidates goes to review (a margin would be a new threshold) |
| 2 | What counts as a human decision to carry over | A correction, merge or split on the face, or a named identity (later also human validation); automatic-only decisions are not carried |
| 3 | Where review items live | Append-only evidence rows (`REPROCESS_REVIEW_REQUIRED`, ids only), no new table |
| 4 | Activate V2 while review items are pending | Yes; holding activation would block the source |
| 5 | Forget against identity model §47 | The same image is the same evidence, so it must not bring a forgotten face back |
| 6 | `parent_run_id` is already retry lineage | Keep it for retry; add a separate `supersedes_run_id` |
| 7 | `process` on an already processed source duplicates occurrences | Refuse it: 409 `SOURCE_ALREADY_PROCESSED` |
| 8 | A second reprocess request while V2 is running | 409 `SOURCE_BUSY`, not an idempotent 202 |
| 9 | Leftover V2 output after a cancel or failure | No new cleanup in this step |
| 10 | Superseded vectors | Kept for audit until forget, erasure or deletion; no automatic purge |
| 11 | A face matching itself during reprocessing | Exclude V1's own representations from V2's recognition pool (a candidate filter, not a threshold change) |

## 3. What is left

**M6** ([plan](M6_PLAN.md), in order):

1. Reprocessing images: versioned runs and atomic supersession (#180), the spec in PR #229 first.
2. Worker arbitration: #175's remaining acceptance tests (batch yields, queued cancellation,
   crash and restart, a stress run with p50/p95 wait) and #221 (one worker process).
3. Video import and probe (needs D2's FFmpeg and PyAV licence check recorded first).
4. Decode, sample at 2 fps (D4) and chunk, with checkpoints.
5. Detect, track (NumPy-only, D6) and select observations.
6. Recognition and occurrences over time (D7: the per-face point on each selected observation, in
   agreement).
7. Pause, resume and cancel, the movie workflow end to end, one heavy movie job at a time, and video
   retry (D10).
8. The real-world check on the owner's own videos (D8).

**M7 and M8:** neither has a plan.

**Open issues and where each belongs:**

| Issue | Where |
|---|---|
| #180 reprocessing | M6 step 1 (PR #229) |
| #175 worker contention | M6 step 2 |
| #221 one worker process | M6 step 2 (D11) |
| #174 network paths | Backlog: refusal by default is built and owner-confirmed; approved network roots are not |
| #176 PDF face search | Backlog, deferred |
| #181 which face carries a label | Backlog |
| #183 LFW and CelebA terms at source | M8 release blocker |

## 4. Release blockers (M8)

- The `buffalo_l` face weights are research-only. The owner accepted this for personal use; it blocks
  any release.
- #183: LFW's own terms page still has to be read. The Kaggle mirror's licence field grants nothing.
- D2: the exact FFmpeg builds' licences, including PyAV's bundled FFmpeg, are to be inspected and
  recorded before M6 step 3 merges.
- The licence inventory of the Rust crates and build tools, and the installer and signing, are not
  done (`docs/research/licensing-and-commercialization.md` section 11).

## 5. Open owner decisions

1. Approve PR #229's spec text and answer its eleven questions (section 2).
2. Two remote branches belong to closed, unmerged PRs and were left in place: `feat/177-hard-negative-selection`
   (PR #196) and `fix/178-verified-operating-point` (PR #187). Their work was superseded by later merged
   PRs (hard negatives and the verified operating point are on `main`). Recommendation: delete both;
   GitHub keeps each closed PR's commits.

## 6. Housekeeping done on 2026-10-28

- 30 worktrees removed after checking each for uncommitted, untracked and ignored data (none held
  data, reports or weights). Kept: the main checkout and PR #229's worktree.
- 46 local branches deleted. 41 had every patch on `main`. The other 5 were pre-rebase copies of
  merged PRs (#199, #200, #203, #206, #212) whose content is on `main`. Kept: `main` and PR #229's two
  branches.
- The remote branch `fix/pr213` deleted (every patch on `main`, through PR #213).
- Eight finished Claude Code side sessions archived. The PR #229 session is kept.
- Three empty folders under `.claude/worktrees/` (`m5-gate-gaps-52956a`, `m5-gates-de2d88`,
  `mystifying-robinson-309f1a`) and `../FI-179` could not be removed: Windows reports them busy
  because another process still holds them, even after their sessions were archived. They hold no
  files and are not git worktrees; delete them after restarting the Claude app.

## 7. How to resume

1. Read `AGENTS.md`, `docs/guides/AGENT_HANDOFF.md`, `.agents/CONTEXT.md` (its dated decisions and
   "Next steps"), every file in `.agents/rules/`, this page and [`M6_PLAN.md`](M6_PLAN.md).
2. Run `git fetch`, `git log --oneline -5 origin/main`, `gh pr list --state open` and
   `gh issue list`, and check them against this page.
3. Rebase PR #229 onto `origin/main` if `main` has moved, re-review its exact head, and bring the
   spec text and its eleven questions to the owner.
4. Only after the owner approves the spec: build M6 step 1 (phase 2 in the PR's plan), one small PR at
   a time, each with an independent read-only review and green CI on its exact head before the
   owner's merge.
