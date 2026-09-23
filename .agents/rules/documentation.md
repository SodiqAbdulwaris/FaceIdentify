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
- If implementation reveals a gap in a spec, record it in the implementation entry and in
  `CONTEXT.md` under *Known conflicts*, then ask the user how to fill it.

## When documents conflict

Specs, plans and other docs sometimes disagree (for example an ERD against the persistence
contract, or a roadmap against the testing tracker). **Never silently pick one.**

1. **Stop and ask the user for a decision** before building on either version.
2. **Always include your recommendation.** For each conflict, quote or cite both sides
   (file and section), list the options, say which one you recommend and why (e.g. newer,
   more specific, matches the other contracts), and note the consequences of each option.
3. **Once the user decides, update the docs** so they agree, in the same PR as the change or a
   dedicated `docs:` PR:
   - edit the losing passage in place with a dated note, e.g.
     `> **Decision YYYY-MM-DD:** … (supersedes the text below)`, rather than deleting the
     history;
   - update every other document that states the losing version (search for it);
   - record the decision in `.agents/CONTEXT.md` (*Known conflicts*, marked resolved) and in the
     implementation entry for the work.
4. A decision the user delegates ("do what you think is best") counts as approval of your
   recommendation, including the spec edits it needs. Say in the docs that it was delegated.
- Do not create new top-level documents when an existing one covers the topic. Place new
  documents in the matching `docs/` folder: `specs/`, `plans/`, `guides/`, `strategy/`,
  `research/` or `archive/`.
