# Owner decisions on M4 and the M5 plan

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 close-out, M5 planning (no tracker row changes)
- **Status:** done (documentation only)
- **Commits:** PR to be recorded when opened

## What changed

- Recorded the owner's answers to the six M4 agent decisions as dated notes in the entries that
  raised them (status route, development catalog, hash routing, `.npmrc`, person label, recycled
  sources). `.npmrc` gained a comment that the setting is repository-wide and temporary.
- Drafted [`docs/plans/M5_PLAN.md`](../plans/M5_PLAN.md) in the owner's order and recorded the owner's
  answers to CONTEXT questions 12, 15 and 16 in `CONTEXT.md` and as notes in
  `PERSISTENCE_IMPLEMENTATION.md` sections 7 and 10.
- Opened issue #137 for the development-profile guard the owner required.

## Why

The owner asked to resolve the pending decisions, then plan M5. Spec conflicts need a recorded
decision before building (`rules/documentation.md`).

## Decisions

All owner decisions, 2026-10-07: see the notes named above. The guard on `--development-profile` is
required but not built; the recycled-source behaviour and the `SPLIT` removal are built with their M5
steps.

## Verification

Documentation only; nothing was run. The links and section numbers cited from the specs were read,
but the M5 plan's claims about existing use-case behaviour (for example Person conflict on merge) are
marked "to verify" in the plan.

## Open issues / follow-ups

- The M5 plan needs the owner's approval, and its "Ask before building" items need answers when each
  step starts.
- Issue #137: development-profile guard.
