# M8: what remains and what depends on M6 and M7

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M8 (planning record, no tracker row moves)
- **Status:** done
- **Commits:** PR (number added when opened): `docs(m8): list what remains and what depends on M6 and M7`

## Why

The M8 brief asks for a written list of what depends on M6 and M7 (for example bundling FFmpeg) and what is left, so the
orchestrating session and the next agent do not have to rebuild that picture from the entries.

## What changed

- `docs/plans/M8_PLAN.md` section 1a: what is built, what is left in M8, that nothing waits for M6 any more (FFmpeg ships), that M7's
  only packaging follow-up is a rebuild (re-freeze, notices, installer) plus two checks on an installed build, and what needs the owner.

## Verification

Docs only. Every statement was checked against the merged entries (steps 1 to 4, the pre-migration copy).

## Open issues / follow-ups

- Section 1 of the plan still describes 2026-11-10; section 1a supersedes it where they differ.
