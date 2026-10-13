# Recognition 04 Decisions in memory

## 1. What this is and why it exists

The reasoner only *proposes*. Nothing changes until acceptance applies each proposal inside the single acceptance transaction
([checkpoints and acceptance](../processing/04-checkpoints-and-acceptance.md)). This lesson follows the three outcomes to the rows
they produce, so you can read a database and say which decision made which row.

## 2. Where it lives

| Thing | Where |
|---|---|
| Applying a decision | `_accept_decision` in `backend/app/processing/accept_run.py` |
| Identity helpers (`activate_identity`, `assign_representation_to_identity`) | `backend/app/identities/use_cases.py` |
| Evidence writing | `EvidenceRepository`, `EvidenceLink` |
| Index operations | `IndexOperationRepository.append_batch` in `backend/app/memory/` |
| Tests | `tests/integration/test_accept_processing_run.py` (for example `test_abstention_candidates_are_historical_evidence`, `test_matched_identity_evidence_keeps_its_candidate_snapshot`) |

## 3. How it works

For each face in the FINAL checkpoint:

| Outcome | Identity | Representation | Evidence | Occurrence | Index |
|---|---|---|---|---|---|
| `CREATE_NEW` | the pending identity made during execution is **activated** | `ACTIVE`, owned by it | `IDENTITY_CREATED` (role `SUBJECT`) + candidates | yes | `ADD` |
| `MATCH_EXISTING` | the matched identity is **unchanged** (its revision moves) | `ACTIVE`, assigned to it | `IDENTITY_MATCHED` + candidates | yes | `ADD` |
| `ABSTAIN` | none | `ACTIVE` **with no identity**, and an `ann_key` | `RECOGNITION_ABSTAINED` + candidates | **no** | `ADD` |

- An abstained representation is still stored and indexed: it is evidence that "a face looking like this was seen", and later
  faces can see it as an identity-less neighbour (it can never be a match target, [assessment](02-assessment.md)). The person
  does not yet exist as an identity.
- The evidence payload is the reasoner's `evidence_payload()` (outcome, reason, thresholds in force, the ranked candidates);
  the same candidates are also stored one row each in `evidence_candidates`.
- Everything above is revalidated against the private rows first (an abstention that secretly names an identity is refused).
- **Corrections later** never rewrite these rows; they add evidence ([identities](../domain/04-identities-and-lineage.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([domain README](../domain/README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select e.kind, count(*) from evidence e group by 1" "select count(*) from occurrences" "select state, ann_key, identity_id is null from representations"
```

Observed: two `IDENTITY_CREATED`, one `IDENTITY_MATCHED`, three occurrences, three `ACTIVE` representations each with an
identity. The development profile never abstains on these pictures, so the abstention rows are shown by tests:

```bash
uv run pytest tests/integration/test_accept_processing_run.py -q -k "abstention or matched"
```

Expected: pass (the abstention test checks that the candidates of an abstained face are kept as historical evidence).

## 5. Change it

A new outcome would touch the enum, the reasoner, this function, the evidence kinds (migration), the index rules and
the front end. Treat it as a design change needing a spec decision, not a patch.

## 6. Break it on purpose

In a scratch edit make `ABSTAIN` skip the `ADD` operation and run `test_accept_processing_run.py`: a test that checks the
index convergence fails, since the abstained face would be invisible to later retrieval. Restore with `git restore`.

## 7. Exercises

1. Which outcome creates no occurrence?
2. Why is an abstained representation indexed?
3. Does a match change the matched identity's history?
4. Where do you find the candidates that were considered?

**Answers**

1. `ABSTAIN`.
2. Later faces can see it as evidence of something similar (never as a match target).
3. No; it adds a representation, an occurrence and evidence. The identity's revision moves.
4. `evidence_candidates`, and the `candidates` list in the evidence payload.

## 8. Related files

- Previous: [03](03-decision-policy.md) · Next: [05 The face query](05-face-query.md)
- [`backend/app/processing/accept_run.py`](../../../../../backend/app/processing/accept_run.py)
