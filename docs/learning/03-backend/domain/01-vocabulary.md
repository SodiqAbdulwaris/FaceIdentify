# Domain 01 Vocabulary

## 1. What this is and why it exists

Most confusion about this codebase is a vocabulary problem: "face", "person", "identity" and "match" sound like one thing
and are four. The spec ([`identity-and-memory-model-v1.md`](../../../specs/identity-and-memory-model-v1.md)) separates them on
purpose, because each can change without the others: you rename a person without re-recognising anything, and you re-run
recognition without touching a name.

## 2. Where it lives

Each noun is one SQLAlchemy model and one table:

| Noun | Meaning | Model (file) |
|---|---|---|
| **Artifact** | one stored file: an original, a crop, a thumbnail, a model file | `Artifact` (`backend/app/sources/models.py`) |
| **Source** | what the user imported (an image; video is designed) | `Source` (same file) |
| **Observation** | one detected face in one source, with a box | `Observation` (`backend/app/memory/models.py`) |
| **Representation** | the vector (embedding) of one observation in one space | `Representation` (same) |
| **Representation space** | one embedder's vector world (dimension, metric) | `RepresentationSpace` (same) |
| **Identity** | the persistent visual subject: "this same face", named or not | `Identity` (`backend/app/identities/models.py`) |
| **Person** | a named human, a *semantic* thing | `Person` (`backend/app/people/models.py`) |
| **Association** | the current/past link of an identity to a person | `IdentityPersonAssociation` (same) |
| **Occurrence** | a meaningful appearance of an identity within a source | `Occurrence` (`backend/app/memory/models.py`) |
| **Evidence** | an immutable record of why a decision was made | `Evidence` (`backend/app/identities/models.py`) |

## 3. How it works

```text
Source ──has──▶ Artifact (original, thumbnail)
  │
  └─ ProcessingRun ──produces──▶ Observation (a face box)
                                    └─▶ Representation (a vector, in a space)
                                              │ belongs to
                                              ▼
                              Identity ◀──── Occurrence (in a Source)
                                 │
                       Association (current/ended)
                                 ▼
                              Person (a name)

Evidence rows record each decision above and cite the representations they used.
```

**The three words people mix up**

- **Match** is a *decision*: a new representation was judged close enough to an existing identity (`MATCH_EXISTING`).
- **Identity** is a *thing that persists*: the visual subject. An identity can be unnamed. An unnamed identity never gets a
  placeholder person.
- **Person** is a *name given by a human*. Many identities may point at one person (the same human looked very different
  in two groups of photographs); one identity has at most one *active* person.

**Authoritative vs derived** ([lesson](../../00-start-here/03-authoritative-and-derived.md)): observation, representation,
identity, occurrence and evidence are authoritative rows. The nearest-neighbour index holds only an `ann_key` per
representation and is rebuildable.

## 4. Try it

**Works with no models. Verified 2026-10-12.** With the practice library ([README](README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select 'sources', count(*) from sources union all select 'observations', count(*) from observations union all select 'representations', count(*) from representations union all select 'identities', count(*) from identities union all select 'people', count(*) from people union all select 'occurrences', count(*) from occurrences union all select 'evidence', count(*) from evidence"
```

Observed: 3, 3, 3, 2, 0, 3, 3. **Three faces, two identities, no people**: the second picture of the red image matched the first
identity, and nobody named anyone. Now trace one face end to end:

```sql
select o.id, r.ann_key, r.identity_id, oc.kind, e.kind
from observations o
join representations r on r.observation_id = o.id
join occurrences oc on oc.source_id = o.source_id
left join evidence e on e.source_id = o.source_id
```

Each row follows an observation to its vector, the identity it was given, its occurrence, and the evidence for the decision.

## 5. Change it

You do not change vocabulary in code lightly: the nouns are in the spec and the tables. A safe documentation exercise: find
a word in the UI (for example "Unnamed identity") and trace it to the table and enum behind it with `grep -rn` in `frontend/src`
and `backend/app`.

## 6. Break it on purpose

Name the same noun two ways in your head ("face" for both observation and representation) and try to answer "what
does re-running recognition replace?" You cannot. The answer is *representations and identity assignments*; the observation
(a box on a picture) is superseded only by a re-run of detection.

## 7. Exercises

1. Can an identity exist without a person?
2. Is the vector stored in the index or in the database?
3. What is the difference between an observation and an occurrence?
4. Which table says *why* an identity was created?

**Answers**

1. Yes; unnamed identities are normal.
2. In the database (`representations.vector`); the index holds only a key and is rebuildable.
3. An observation is one detected face in one source; an occurrence is an identity's appearance in a source and may group
   several observations (designed for video tracks).
4. `evidence` (with `evidence_representations` and `evidence_candidates`).

## 8. Related files

- Next: [02 Sources and artifacts](02-sources-and-artifacts.md)
- [`docs/specs/identity-and-memory-model-v1.md`](../../../specs/identity-and-memory-model-v1.md), [`docs/specs/ERD.md`](../../../specs/ERD.md)
