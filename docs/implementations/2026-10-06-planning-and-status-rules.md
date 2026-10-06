# Rules: plans in docs/plans and a project status page

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** process (no tracker ID)
- **Status:** done (docs only)
- **Commits:** this docs-only PR: `docs(rules): require plans in docs/plans and a status page`

## What changed

- `.agents/rules/documentation.md` gained two sections, *Plans* and *Project status*, and a fifth
  item under *For every change*: update the status page when what is built changes.
- `AGENTS.md` gained a non-negotiable bullet pointing at both.
- New `docs/plans/PROJECT_STATUS.md`: a one-page overview of what is built and where the project
  stands, one row per area, each linking to the implementation entries for detail.
- `.agents/CONTEXT.md` repository map mentions both.

## Why

The owner asked for implementation plans to live in `docs/plans/` (not only in chat) and for a
short, glanceable overview of what has been built that points at the detailed entries.

## Decisions

> **Decision 2026-10-06:** the owner asked for these two rules. Placing the status page at
> `docs/plans/PROJECT_STATUS.md` (rather than a new top-level `docs/` file) was the agent's choice,
> to avoid a new top-level document; say so if you would rather it live elsewhere.

## Verification

Docs only; no code or test changed. Every link in `PROJECT_STATUS.md` was checked to point at an
existing file, and its statuses were written from the current `CONTEXT.md`, tracker and merged PRs.

## Open issues / follow-ups

Agents must now refresh `PROJECT_STATUS.md` in each PR that moves the project. The M3.1 PR (in
review when this was written) will update its "M3 remaining" row when it merges.
