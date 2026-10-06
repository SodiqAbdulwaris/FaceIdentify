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
5. **Update [`docs/plans/PROJECT_STATUS.md`](../../docs/plans/PROJECT_STATUS.md)** when the change
   alters what is built or where the project stands (see *Project status* below).

## Plans

An **implementation plan** is written down in [`docs/plans/`](../../docs/plans/) before the work
starts, never only in chat or in an agent's private plan file. Write one for anything that spans
several PRs, a milestone or a workstream, or that needs the owner's decisions; a one-PR change does
not need one (its implementation entry is enough).

- One file per plan, named `<TOPIC>.md` (for example `M3_M4_COMPLETION_PLAN.md`). Extend an existing
  plan instead of starting a second one for the same work.
- A plan states: the goal and scope (and what is out of scope), the steps in order, dependencies
  and blockers, the owner's decisions (as dated `> **Decision YYYY-MM-DD:**` notes), the tracker IDs
  it serves and its definition of done.
- Keep it true as the work proceeds: mark finished steps, record changes of approach, and link the
  implementation entries that delivered each step. A plan that no longer matches reality is a bug.
- Link it from [`.agents/CONTEXT.md`](../CONTEXT.md) and from `PROJECT_STATUS.md`.

## Project status

[`docs/plans/PROJECT_STATUS.md`](../../docs/plans/PROJECT_STATUS.md) is the one-page overview the
owner can glance at to see what has been built and where the project stands. It is a map, not a
log, so keep it short and plain.

- One row per area or milestone: its status (done, in progress, blocked, not started), a line on
  what exists, and links to the implementation entries for detail ("for more details see ...").
- It says what is **not** built yet, and the current blockers and open decisions.
- Update it in the same PR as any change that alters what is built or the project's position, and
  set its *Last updated* date. Status follows the honesty rules below: only what you verified.
- It does not repeat test counts, commit lists or design detail. Those live in the implementation
  entries and the tracker.

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
  `CONTEXT.md` under *Known conflicts and open questions*, then ask the user how to fill it.
- Do not create new top-level documents when an existing one covers the topic. Place new
  documents in the matching `docs/` folder: `specs/`, `plans/`, `guides/`, `strategy/`,
  `research/` or `archive/`.

## When documents conflict

Specs, plans and other docs sometimes disagree (for example an ERD against the persistence
contract, or a roadmap against the testing tracker). **Never silently pick one.**

1. **Stop and ask the user for a decision** before building on either version.
2. **Always include your recommendation.** For each conflict, quote or cite both sides
   (file and section), list the options, say which one you recommend and why (e.g. newer,
   more specific, matches the other contracts), and note the consequences of each option.
3. **Once the user decides, update the docs** so they agree, in the same PR as the change or a
   dedicated `docs:` PR:
   - keep the losing passage and add a note directly after it (or after its heading), always in
     this exact format: `> **Decision YYYY-MM-DD:** <what was decided, and the authoritative
     source>`. Never delete the superseded text. Put notes at the end of a paragraph or list,
     never inside one;
   - update every other document that states the losing version. Search for all its
     wordings and related terms, not just one phrase (e.g. for a merge-level decision:
     `merge`, `MERGED`, `split`, `canonical_person`, `PERSON_`);
   - record the decision in `.agents/CONTEXT.md` (*Known conflicts*, marked resolved) and in the
     implementation entry for the work.
4. A decision the user delegates ("do what you think is best") counts as approval of your
   recommendation, including the spec edits it needs. Say in the docs that it was delegated.
