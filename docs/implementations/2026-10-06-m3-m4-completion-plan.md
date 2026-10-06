# M3 and M4 completion plan

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M3 close-out, M4 planning
- **Status:** done (docs only)
- **Commits:** this docs-only PR: `docs(plans): plan the rest of M3 and M4`

## What changed

Added `docs/plans/M3_M4_COMPLETION_PLAN.md`: the remaining M3 work and blockers, the M3 exit gate,
the M4 workstreams (W1 to W8) and their order, dependencies, tracker mappings and the M4 definition
of done. Recorded the owner's six decisions plus the recovery-before-scheduler constraint, with
dated notes in the plan, Persistence section 15 (job priority) and `CONTEXT.md` (question 14 and
the M3 item).

## Why

The owner asked for the rest of M3 and M4 to be planned before more code is written.

## Decisions

> **Decision 2026-10-06:** the six decisions (development policy profile, weights blocked on
> issue #69, integer priority rank in revision `0007`, stdout JSON handshake with an environment
> token, TanStack Query plus Zustand plus `openapi-typescript`, local `runtime/` development install)
> and the constraint that recovery completes before the scheduler claims work. Full text in the plan.

## Verification

Docs only; no code or test changed. Links and tracker IDs were checked against
`TESTING_IMPLEMENTATION_TRACKER.md` and the specs.

## Open issues / follow-ups

Next: M3.1 / issue #66 (move the eraser and recovery writes onto `UnitOfWork`), then the rest of M3
before M4 begins.
