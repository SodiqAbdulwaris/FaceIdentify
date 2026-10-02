# Decisions: the persisted state of a representation space and what its component version means

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M3 (step 7); documentation only
- **Status:** done for decisions 1 and 3; decision 2 (the manifest `contract` keys) awaits the owner's confirmation
- **Commits:** PR (this branch): `docs: record the space-state and provenance decisions in the specs`, `docs: record the decisions in CONTEXT and the implementation log`, `docs: annotate the activation wording and scope the state note`

## What changed
Dated `Decision 2026-10-02` notes, in the format `.agents/rules/documentation.md` requires (the losing text kept, the note after it):
- Persistence 6.1 (after the section's text): the two persisted states `ACTIVE`/`DEPRECATED` stand; `REGISTERED`/`VALIDATED` are registration steps, not persisted states; `RETIRED` is `DEPRECATED`; a valid newly registered space is `ACTIVE`; `component_version_id` is origin provenance; the invariant that space identity describes compatibility and execution provenance describes what produced the data.
- Persistence, the paragraph on new embedding models: a new component version with identical space-defining identity shares the space; a new model is a new space.
- ML spec 9.2, after the list of operational states: that list is a registration process followed by a lifecycle, and only the lifecycle of a `RepresentationSpace` is persisted (a variant's, export's or package's own `state` column is a separate vocabulary, still open question 11).
- ML spec 9.3 and 15, where the upgrade sequence says "activate" (and, in 9.3, "register" before "validate"): "activate" is a selection in the processing configuration, not a persisted state of the space; validation precedes registration. Rollback is likewise a configuration change. (The first version of this change missed these two passages; the independent review found them.)
- CONTEXT question 31 (decisions 1 and 3 recorded, 2 left open with the keys listed); the earlier registration entry points at it.

## Why
The owner decided, 2026-10-02, on the agent's recommendations recorded in open question 31 (found building registration and raised in the PR 85 review). Other documents were searched for the losing wording: the `RETIRED` hits in the ERD are other entities in a conceptual document.

## Decisions
The owner's wording is the source: "Space identity describes compatibility; execution provenance describes what produced data." The registration code (`registration.py`) already behaves this way (spaces are created `ACTIVE`, an existing space is reused and its `component_version_id` is never overwritten), so no code changes.

## Verification
Documentation only. The notes sit after the paragraph or list they qualify, never inside one. Nothing else changes, so the code gate is the one already on `main`.

## Open issues / follow-ups
- Decision 2: the manifest `contract` keys (a note in Architecture 12.2 follows the owner's confirmation).
- Execution provenance of the embedder: per-observation provenance records the detector's component version; recording the embedder's actual component version and runtime variant per representation is for the PENDING-output writer (step 7, last part) to settle against the existing columns, and to raise as a gap if they do not suffice.
