# Align specs with the M1 decisions and add the doc-conflict rule

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 prerequisites
- **Status:** done
- **Commits:** PR #3: `docs(specs): align specs with the m1 schema decisions`, `docs(agents): require decisions with recommendations for doc conflicts`, `docs: record spec alignment and m1 plan`, plus the review fixes `docs(specs): complete decision notes after review` and `docs: tighten doc-conflict rule and entry after review`

## What changed

- **Specs aligned** with the owner's decisions of 2026-09-23. Each superseded passage keeps its
  original text and gains a `> **Decision 2026-09-23:**` note:
  - `ERD.md` (header): conceptual, not the implementation schema.
  - `IMPLEMENTATION_ARCHITECTURE.md` (end of §26): schema comes from persistence, not an ERD mapping.
  - `Roadmap-Plan.md` §13 and §47: uuid4 instead of UUIDv7. §60: the domain-level Phase A–E work
    (naming, query guard, corrections, merge, split; TST-011–020) is built in testing milestone M1.
  - `PERSISTENCE_IMPLEMENTATION.md` §7: domain-level merge/split are M1; "later" means UI/integration.
  - `identity-and-memory-model-v1.md` §18, §19.1, the reconciliation events list, and locked
    decision 23: merge is Identity-level; Person-level operations are association changes.
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
| Merge level | Person-level (identity model) vs Identity-level (persistence, API, roadmap) | Identity-level. **Initially not asked**, which broke the new rule; the review caught it and the owner confirmed Identity-level explicitly |

## Verification

- First pass: `grep` for `UUIDv7`, `canonical_person`, `status: MERGED` and the ERD status.
  The subagent review found passages this search missed (§19.1, `PERSON_MERGED/SPLIT`,
  decision 23, persistence §7, roadmap §60, architecture §26). They were fixed, and the rule now
  requires searching all related terms.
- Every note was checked in rendered context (end of a paragraph or list, never inside one).
- Relative links in the changed agent docs resolve.

## Open issues / follow-ups

- ERD sections still describe tables that won't be built (e.g. `domain_event`). The status note
  covers them; no per-section edits were made.
