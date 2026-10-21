# M6 plan approved
- **Date:** 2026-10-21
- **Milestone / tracker IDs:** M6 (TST-060 to TST-070), issues #180, #175, #221
- **Status:** done; documentation only (no code, threshold, policy, model, dependency or spec changed)
- **Commits:** PR (number recorded when merged): `docs:` commits on `docs/m6-plan-approved`

## What changed

The owner's approval is recorded: "I accept all twelve M6 recommendations (D1 to D12 as you laid them out) and approve the M6 plan." (2026-10-21).

- `docs/plans/M6_PLAN.md`: title and status now say approved (2026-10-21); section 1 has a dated note that M5 is complete (2026-10-21, `a778d81`); section 7 became recorded decisions D1 to D12 (D5 reworded, D11 and D12 added); step 2 now includes #221 and its acceptance; sections 4 and 5 mention #221 and the per-step spec and licence conditions. Everything else stands.
- `.agents/CONTEXT.md`: a dated decision note, the milestone line, "Last updated" and "Next steps" (M6 step 1, #180, under D3 and D1).
- `docs/plans/PROJECT_STATUS.md`: the M6 row is in progress (plan approved 2026-10-21), "What is next", the open-decisions text, and the #180 and #221 rows.

## Why

The M6 plan was a draft with ten open decisions (D1 to D10). The owner decided all of them as recommended and added D11 (#221 into step 2) and D12 (plan approval).

## Decisions

D1 spec changes approved per step (each step's PR proposes its exact text, so this PR adds no spec text); D2 the locked stack (pinned LGPL FFmpeg + ffprobe, PyAV, no GPL components), with the builds' licences recorded before step 3 merges; D3 reprocessing carries a human decision over only within the same compatible `RepresentationSpace`, same source, box IoU >= 0.7, embedding cosine >= 0.9, one-to-one, else review; D4 2 fps configurable; D5 3 consecutive interactive grants, benchmarked in step 2; D6 NumPy-only tracker; D7 per-face 0.45 / 0.10 on each selected observation, in agreement; D8 the owner's own local videos, generated CI fixtures; D9 reprocessing is step 1; D10 resume from the last valid checkpoint if the snapshot is runnable, else a new run; D11 #221 into step 2; D12 plan approved.

## Verification

Documentation only. `git diff --check`, CRLF preserved in every edited file, every cited sha (`a778d81`) checked with `git merge-base --is-ancestor` against `origin/main`, and a search that no current-status text still calls the M6 plan a draft or its decisions open (dated history stays).

## Open issues / follow-ups

M6 step 1 (#180) is next; its PR proposes the spec text (D1). Step 3's PR needs the licence inspection recorded first (D2). No spec was edited.
