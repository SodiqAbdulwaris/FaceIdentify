# Align specs with the M1 decisions and add the doc-conflict rule

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 prerequisites
- **Status:** done
- **Commits:** PR on `docs/align-specs-with-decisions`: `docs(specs): align specs with the m1 schema decisions`, `docs(agents): require decisions with recommendations for doc conflicts`, `docs: record spec alignment and m1 plan`

## What changed

- **Specs aligned** with the owner's decisions of 2026-09-23. Each superseded passage keeps its
  text and gains a dated decision note:
  - `docs/specs/ERD.md` status: conceptual, not the implementation schema; the persistence spec wins.
  - `docs/plans/Roadmap-Plan.md` §13 and §47: uuid4 instead of UUIDv7. §63: domain-level
    merge/split and TST-015/016 move to testing milestone M1; Phases D/E keep the API/UI/ML integration.
  - `docs/specs/identity-and-memory-model-v1.md` §18: merge is Identity-level; the Person-level
    example is conceptual.
- **New rule** in `.agents/rules/documentation.md` (*When documents conflict*), linked from
  `AGENTS.md`: agents ask the owner with a recommendation, then update every affected doc.
- `.agents/CONTEXT.md`: conflicts 7–10 marked resolved, and the agreed 8-PR M1 plan recorded.

## Why

While planning M1, the specs disagreed on the schema (ERD vs persistence), identifier format
(UUIDv7 vs uuid4), merge level (Person vs Identity) and when merge/split is built. The owner
chose the recommended option for each, asked for the docs to be updated to match, and asked for
a standing rule on handling future doc conflicts.

## Decisions (all by the owner, 2026-09-23)

| Conflict | Options | Decision |
|---|---|---|
| Schema source | ERD vs PERSISTENCE_IMPLEMENTATION.md | Persistence (newer, concrete; API and roadmap match) |
| Identifier | UUIDv7 (roadmap) vs uuid4 (persistence) | uuid4 |
| M1 scope | merge/split in M1 (tracker) vs after the first milestone (roadmap) | All of TST-011–020 in M1 |
| Merge level | Person-level (identity model) vs Identity-level (persistence, API, roadmap) | Identity-level. Not asked separately: the three newer docs agree, so the older one was annotated |

## Verification

- `grep` for `UUIDv7`, `canonical_person` / `status: MERGED` and the ERD status across `docs/`:
  each hit is either updated or annotated with the decision note.
- Relative links in the changed agent docs resolve.

## Open issues / follow-ups

- ERD sections still describe tables that won't be built (e.g. `domain_event`). The status note
  covers them; no per-section edits were made.
