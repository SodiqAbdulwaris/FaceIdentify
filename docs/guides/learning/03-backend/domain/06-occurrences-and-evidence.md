# Domain 06 Occurrences and evidence

## 1. What this is and why it exists

Two questions the product must answer: **"where does this identity appear?"** (an **occurrence**) and **"why did the
application decide that?"** (**evidence**). Evidence is the trust mechanism: every automatic or manual decision about memory
leaves an immutable record naming the decision, the representations it used, the candidates it considered and the policy that
judged them. A wrong decision can then be explained, and corrected without rewriting history.

## 2. Where it lives

| Thing | Where |
|---|---|
| `Occurrence`, `OccurrenceObservation`, `OccurrenceKind`, `OccurrenceState` | `backend/app/memory/models.py` |
| `Evidence`, `EvidenceKind`, `EvidenceRepresentation`, `EvidenceCandidate` | `backend/app/identities/models.py` |
| Writing them at acceptance | `AcceptProcessingRunUseCase` in `backend/app/processing/accept_run.py` (`_candidates`) |
| Tests | `tests/integration/test_accept_processing_run.py`, `test_memory_models.py` |

## 3. How it works

- **Occurrence**: one identity within one source, `kind` `IMAGE`, `TRACK` or `SEGMENT` (only `IMAGE` is built; the others
  are designed for video). A check says an `IMAGE` occurrence has no frame or time range. `OccurrenceObservation` lists
  the member observations in order, and `representative_observation_id` is the one shown. States `PENDING` → `ACTIVE`
  at acceptance; `SUPERSEDED` is *designed* for when a re-run replaces it but is not set by any code today; `DELETED`.
- **Evidence** is append-only. Its `kind` says what happened: `IDENTITY_CREATED`, `IDENTITY_MATCHED`, `RECOGNITION_ABSTAINED`,
  `IDENTITY_ASSIGNED_TO_PERSON`, `IDENTITY_REMOVED_FROM_PERSON`, `IDENTITY_MERGED`, `IDENTITY_SPLIT`, `IDENTITY_FORGOTTEN`,
  `USER_CORRECTION`, `PERSON_RENAMED`, `SOURCE_PERMANENTLY_DELETED`. It names the run, source, identity and person involved
  and carries a versioned JSON `payload_json`. `superseded_at` is an explanatory marker only; the payload is never rewritten.
- **A recognition payload** (schema version 1) holds: `outcome` (`CREATE_NEW`, `MATCH_EXISTING` or `ABSTAIN`), `reason`,
  the `identity_id`, the `representation_id` and `ann_key`, the `assessment_version`, the `interpretation`
  (`COSINE_UNCALIBRATED` on the development profile), the `quality`, the `retrieval` summary (`requested_k`, `returned`,
  `dropped`, `converged`) and the ranked `candidates`, each with its member representations.
- **`evidence_representations`** links evidence to the representations it cites with a role (`SUBJECT`, `SELECTED_CANDIDATE`,
  `CANDIDATE`, `SUPPORTING`). **`evidence_candidates`** keeps each considered candidate in rank order with `raw_similarity`,
  `calibrated_confidence` (empty until a calibrated policy exists) and `decision`.
- **Evidence never contains a name** and never the photograph; it is ids and numbers.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([README](README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select e.kind, er.role, json_extract(e.payload_json, '\$.outcome'), json_extract(e.payload_json, '\$.reason') from evidence e left join evidence_representations er on er.evidence_id = e.id" "select rank, round(raw_similarity, 3), calibrated_confidence, decision from evidence_candidates" "select kind, state, activated_at is not null from occurrences"
```

Observed: `('IDENTITY_CREATED', 'SUBJECT', 'CREATE_NEW', ...)` twice and `('IDENTITY_MATCHED', 'SUBJECT', 'MATCH_EXISTING', 'MATCHED')`.
For the matched face the candidate list is rank 1 with similarity `1.0` (the identical picture) and rank 2 with `0.208` (the
green picture, an unrelated vector); `calibrated_confidence` is `None`. Three occurrences, all `('IMAGE', 'ACTIVE', 1)`.
Read the full payload of the match to see the ranked candidates:

```bash
uv run python q.py ~/faceidentify-play/lib "select payload_json from evidence where kind = 'IDENTITY_MATCHED'"
```

## 5. Change it

Never edit evidence. A new kind of decision adds an `EvidenceKind` value (a database check list, so a migration), a payload
schema version, the writer in the use case, and a test that the row is written with the right links
([migrations](../../02-data-and-storage/04-migrations-alembic.md)).

## 6. Break it on purpose

In a copy of the database, delete one `evidence` row that a lineage row cites: the foreign key (`RESTRICT`) refuses it.
History cannot lose the reason for a merge by accident.

## 7. Exercises

1. What does `calibrated_confidence = None` tell you?
2. Why is an occurrence separate from an observation?
3. How would you find out why a face was matched to an identity?
4. Which table would show an abstention?

**Answers**

1. The policy was not calibrated; only the raw similarity exists.
2. An occurrence is an identity's appearance and may group several observations (video); an observation is one detected face.
3. Read the `IDENTITY_MATCHED` evidence for its run and source: outcome, reason and ranked candidates.
4. `evidence` with `kind = 'RECOGNITION_ABSTAINED'` (its representation has no identity).

## 8. Related files

- Previous: [05](05-people-and-naming.md) · Next: [07 States, revisions and provenance](07-states-revisions-provenance.md)
- [`backend/app/identities/models.py`](../../../../../backend/app/identities/models.py), [decision policy](../recognition/03-decision-policy.md), [decisions in memory](../recognition/04-decisions-in-memory.md)
