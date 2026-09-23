# Documentation rules

**Agents must document everything they do.** Undocumented work is unfinished work.

## For every change

1. **Add an implementation entry** in [`docs/implementations/`](../../docs/implementations/),
   following that folder's `README.md` template. Record what changed, why, the decisions made, how
   it was verified, and what is still open. One entry per task; update it rather than creating a
   second one for the same task.
2. **Update [`.agents/CONTEXT.md`](../CONTEXT.md)** with the current state, new commands, newly
   found conflicts and the next steps. It must stay true: remove stale statements.
3. **Update trackers** (for example `docs/plans/TESTING_IMPLEMENTATION_TRACKER.md`) with
   *verified* status only. Never mark something complete that you have not run.
4. **Update guides** in `docs/guides/` when you change how something is run, configured or
   extended.

## Honesty in documentation

- Separate what was **verified** (you ran it and saw the result) from what is **assumed**.
- Record failures, skips, workarounds and open questions. Do not smooth them over.
- Write dates as absolute dates (`2026-09-23`), never "today" or "last week".
- Cite commits by PR number and commit subject, not SHA. Rebase merges rewrite SHAs, so a SHA
  cited before merging no longer exists on `main`. SHAs are fine only for commits already on
  `main`.

## Authoritative specs

- `docs/specs/` contains the authoritative architecture and contracts. **Do not edit specs
  without the user's explicit approval.**
- If implementation reveals a conflict or gap in a spec, record it in the implementation entry
  and in `CONTEXT.md` under *Known conflicts*, then ask the user how to resolve it.
- Do not create new top-level documents when an existing one covers the topic. Place new
  documents in the matching `docs/` folder: `specs/`, `plans/`, `guides/`, `strategy/`,
  `research/` or `archive/`.
