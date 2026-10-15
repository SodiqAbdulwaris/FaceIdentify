# Evaluation 07 Milestones, the tracker and decisions

## 1. What this is and why it exists

A project this size is only understandable with a map: **what is built, what is next, what was decided and why**. Five documents are
that map, and each answers a different question. Knowing which to open saves hours, and knowing which one is *authoritative* for what
stops you from trusting a stale one.

## 2. Where it lives

| Question | Open | Size |
|---|---|---|
| What is built and where are we? | `docs/plans/PROJECT_STATUS.md` | 45 lines: one row per area, a "not built yet" list, blockers |
| What is the next piece of work, in order? | `docs/plans/M5_REMAINING_WORK.md`, `M5_PLAN.md` (and `M3_M4_COMPLETION_PLAN.md` for the finished milestones) | 85, 374, 114 |
| Is this behaviour tested, and does the test pass? | `docs/plans/TESTING_IMPLEMENTATION_TRACKER.md` (rows `TST-nnn` with a status) | 402 |
| What was decided, and what is open? | `.agents/CONTEXT.md` ("Known conflicts and open questions", numbered, plus the owner decisions inside the plans as dated `> **Decision YYYY-MM-DD:**` notes) | 477 |
| What happened when a specific change was made? | `docs/implementations/` (one entry per change; 136 files including its README; newest by date prefix) | |
| What must the system do? | `docs/specs/` (authoritative; edit only with the owner's approval) | |
| Where did the long-range roadmap start? | `docs/plans/Roadmap-Plan.md` | 2646 |

## 3. How it works

- **Milestones**: M0 foundation, M1 domain, M2 persistence, M3 ML worker and single-image pipeline, M4 API and desktop (development profile),
  M5 the first real recognition milestone (**in progress**), then M6 to M8 (movies, cameras, packaging) not started. Status follows
  [`PROJECT_STATUS.md`](../../../plans/PROJECT_STATUS.md), the single page to trust for "where are we".
- **Tracker statuses** (a legend at its top): `PLANNED`, `IN_PROGRESS`, `BLOCKED`, `PASSING` (the implemented test currently passes) and
  `COMPLETE` (test, docs, CI and review all finished). A row is marked only when verified; **this restructure marks none**. Example of honesty:
  `TST-057A` is `PASSING` with "recognition quality explicitly unverified"; `TST-057B` (automatic recognition) is `BLOCKED` pending calibration.
- **Decisions** are written where they live: a dated `Decision` note in the plan, a numbered item in `CONTEXT.md`, and the reasoning in the
  implementation entry. When documents disagree, the rule is: **ask the owner, with a recommendation, then update every affected document**
  ([documentation rules](../../../../.agents/rules/documentation.md)).
- **The "assisted vs automatic" decision** (owner, 2026-10-08) is the best example to read end to end: the measured operating point said
  automatic matching is unsafe on the current set; the owner split TST-057 into assisted (A: ranked suggestions plus confirmation, built and
  passing) and automatic (B: blocked until verified calibration); the abstain-only policy file is how the code enforces it
  ([decision policy](../03-backend/recognition/03-decision-policy.md)).
- **GitHub issues** hold decided-but-unbuilt work and provisional decisions to validate (for example #69 for the model licence, #80).
- **Honesty rules** for every document: separate verified from assumed, record failures and skips, use absolute dates, cite commits by PR
  number and subject (not SHA).

> **Decision 2026-10-15:** the owner decided to enable automatic acceptance (automatic cross-source recognition, TST-057B): "the we're enabling auto-acceptance, we can do that". The 2026-10-14 conditions 1 to 4 were met on 2026-10-15 (48-identity verified set, hard negatives, the conservative rule on a verified manifest with zero false accepts); this is the code change of condition 5: `require_abstain_first` became `require_approved_policy` in `backend/api/real.py`, which admits a matching policy only when it equals an operating point in `APPROVED_MATCHING` (a policy file alone still cannot enable matching; automatic new identities stay off). **The operating point is pending owner confirmation** (recommended: threshold 0.45, margin 0.10; options and evidence in [`docs/implementations/2026-10-15-enable-automatic-acceptance.md`](../../../../docs/implementations/2026-10-15-enable-automatic-acceptance.md)); until it is confirmed and the policy file is installed, the running application stays abstain-only and TST-057B stays `BLOCKED`.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Answer four questions using only these documents and `grep` (each is a minute's work):

```bash
grep -n "TST-057" docs/plans/TESTING_IMPLEMENTATION_TRACKER.md | cut -c1-120      # the two rows and their statuses
grep -c "PASSING" docs/plans/TESTING_IMPLEMENTATION_TRACKER.md                   # how many rows pass (47 lines mention it)
ls docs/implementations | tail -5                                                # the newest entries
grep -n "New to the code" docs/plans/PROJECT_STATUS.md                           # the one link to this guide
```

Observed: `TST-057A` shows `PASSING` and `TST-057B` shows `BLOCKED`; `PASSING` appears on 47 lines (rows plus legend and prose, so not a precise count of tests);
`docs/implementations/` holds 136 files (its README plus the entries). Then open `PROJECT_STATUS.md` and find, in under two minutes: the current milestone, one thing that is
**not** built, and the open blocker (the model licence).

## 5. Change it

When your change moves what is built: update the matching `PROJECT_STATUS.md` row and its *Last updated* date, add your entry link, update
`CONTEXT.md` ("Current state", "Next steps") and remove statements that became false. Mark a tracker row only after you ran its test and saw it pass.

## 6. Break it on purpose

Read two documents that disagree (this repository has had such cases and records them under "Known conflicts"). The practice: do not pick a
winner silently; ask the owner with a recommendation. A stale doc is a bug.

## 7. Exercises

1. Which document do you update when a milestone's status changes?
2. What does `PASSING` not mean?
3. Where is the reasoning behind a decision?

**Answers**

1. `docs/plans/PROJECT_STATUS.md` (and the tracker and `CONTEXT.md`).
2. That the work is `COMPLETE`: docs, CI and review must also be finished.
3. The dated decision note in the plan, the numbered item in `CONTEXT.md` and the implementation entry.

## 8. Related files

- Previous: [06](06-rules-branches-reviews.md) · Up: [Evaluation and operations](README.md)
- [`docs/plans/PROJECT_STATUS.md`](../../../plans/PROJECT_STATUS.md), [`.agents/CONTEXT.md`](../../../../.agents/CONTEXT.md), [`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`](../../../plans/TESTING_IMPLEMENTATION_TRACKER.md)
