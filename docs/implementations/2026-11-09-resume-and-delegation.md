# Work resumed; delegation recorded
- **Date:** 2026-11-09
- **Milestone / tracker IDs:** M6 (TST-060 to TST-070), M7, M8; issues #180, #175, #221
- **Status:** done; documentation only (no code, threshold, policy, model, dependency or spec changed)
- **Commits:** PR (number recorded when merged): `docs:` commits on `docs/resume-and-delegation`

## What changed

The owner resumed the work paused on 2026-10-28 and made four decisions, recorded in their words:
"Finish up, complete and test this project for me"; on PR #229: "accept all 11 and i'll leave the rest of the decisions entirely to you"; later spec text: "Delegate to me"; merges: "Claude merges"; scope: "Everything through M8" (2026-11-09; the last four were answers to four questions the agent asked).

- `.agents/CONTEXT.md`: a dated decision note, "Last updated" and "Next steps".
- `docs/plans/PROGRESS.md`: the status line says resumed; the 2026-10-28 snapshot stays as history.
- `docs/plans/PROJECT_STATUS.md`: "Last updated", "What is next" and the M6 row.
- PR #231 (the resume prompt and cleanup record; reviewed with no findings, six checks green) was
  rebase-merged by the agent under decision 3.

## Why

Every remaining step was gated on the owner: PR #229's spec text and eleven questions (D1), each later
step's spec text, and every merge. The owner removed those gates for this run.

## Decisions

1. **PR #229 approved.** The spec text is approved and the eleven questions are decided as recommended
   (`docs/plans/PROGRESS.md` section 2, questions 1 to 11).
2. **Delegation.** D1's per-step spec approval, and the remaining product and design decisions, are
   delegated to the agent for M6, M7 and M8. A spec change is still proposed in its PR, independently
   reviewed, and written as a dated note marked as a delegated decision. The owner may reverse any.
3. **Merges.** The agent rebase-merges a PR once an independent read-only review is posted, every
   finding is answered and all six CI checks are green on the exact head.
4. **Scope.** M6, then M7 (cameras) and M8 (a personal-use installer). M7 and M8 get a plan in
   `docs/plans/` before any code.

Not delegated and unchanged: the research-only `buffalo_l` weights block any public release; the live
policy file is installed only by the owner; biometric data and weights stay in their Git-ignored
folders; tests are never weakened; the locked stack is not changed.

## Verification

Documentation only. `git diff --check`; CRLF preserved in every edited file. PR #231's review comment
and its six green checks were read with `gh` before the merge.

## Open issues / follow-ups

M6 step 1 (#180): merge PR #229 after re-reviewing its exact head, then build it. The M6 real-world
check (D8) needs videos of the owner's own; if none is on the machine it stays open and is said so.
