# Routes: corrections (`backend/api/routes/corrections.py`)

## 1. What this is and why it exists

Recognition makes mistakes, and when it is not sure it **abstains** and leaves a face for you. This module is how
you fix both: say "yes, this face is that identity" (**confirm**), say "no, it belongs to someone else" or "it is
nobody I know" (**move** or **separate**), and place the faces recognition declined to place (**resolve**). Every
correction is recorded as an append-only `USER_CORRECTION` Evidence row; the earlier decision is never rewritten.
The API spec gives no route for corrections, so these routes are the agent's design, approved by the owner on
2026-10-08.

## 2. Where it lives

| Route | Use case (`backend/app/identities/corrections.py`) |
|---|---|
| `GET /api/v1/occurrences/{id}` | reads one face (an `OccurrenceSummary`) |
| `POST /api/v1/occurrences/{id}/confirm` | `confirm_occurrence` |
| `POST /api/v1/occurrences/{id}/reassign` | `reassign_occurrence` |
| `GET /api/v1/sources/{id}/unresolved-faces` | a query over active representations with no identity; `_likely` adds hints from the abstention Evidence |
| `POST /api/v1/representations/{id}/resolve` | `resolve_representation` |

Tests: `tests/integration/test_api_corrections.py`, `test_corrections.py`, `test_api_memory.py`.

## 3. How it works

A **face** here is an *Occurrence*: the appearance of an Identity in a Source, resting on an observation and the
vector made from it. The key design points:

- **Ownership moves, nothing else.** A correction changes which identity owns the occurrence and the ACTIVE
  representations made from its observations. The vector and its index entry (`ann_key`) are untouched, so no index work
  is queued.
- **No "cannot link" memory.** A correction does not stop recognition from choosing the same identity for a similar face
  later (owner decision 2026-10-07).
- **The stale-view guard.** Every call carries `expected_identity_id`: the identity *you saw the face under*. If the face
  has moved since, the answer is `409 OCCURRENCE_MOVED` ("This face now belongs to someone else. Reload and try again.")
  instead of applying a correction to something you did not see.
- Both write routes return the occurrence as it now is, and publish `occurrence.updated`.

Requests:

- `confirm`: `{"expected_identity_id": "<uuid>"}`. Records that you agree. `409 FACE_NOT_CORRECTABLE` otherwise.
- `reassign`: `{"expected_identity_id": "<uuid>", "identity_id": "<uuid> | null"}`. A uuid moves the face to that
  (active) identity; **`null` separates it into a new unknown identity** ("This is someone new").
- `resolve`: `{"identity_id": "<uuid> | null"}` for a representation that has *no* identity (an abstention). A uuid
  attaches it to that identity; `null` creates a new unknown identity, **associates the face, creates its Occurrence and
  writes `USER_CORRECTION` Evidence citing the abstention**. `409 FACE_NOT_RESOLVABLE` if it cannot be resolved.
- `unresolved-faces` answer: `{"items": [{"representation_id", "observation_id", "bounding_box", "likely": [{"identity_id",
  "person", "similarity"}]}]}`; `likely` is up to three identities it resembled most, best first. It is a hint, not a
  decision: the abstention is history, the hint is recomputed live from faces that still exist.

## 4. Try it

**Works with no models for confirm, move and separate; unresolved faces cannot be produced by hand on the development
profile. Verified 2026-10-12** (variables as in [call the API](../01-call-the-api.md)).

```bash
OCC=$(curl -s -H "$H" "$B/api/v1/sources/$SRC/occurrences" | j "d['items'][0]['id']")
ID=$(curl -s -H "$H" $B/api/v1/occurrences/$OCC | j "d['identity_id']")
curl -s -X POST -H "$H" -H "$J" -d "{\"expected_identity_id\":\"$ID\"}" $B/api/v1/occurrences/$OCC/confirm | j "(d['id'][:8], d['identity_id'][:8])"
curl -s -X POST -H "$H" -H "$J" -d "{\"expected_identity_id\":\"$OTHER\"}" $B/api/v1/occurrences/$OCC/confirm    # wrong view: 409
curl -s -X POST -H "$H" -H "$J" -d "{\"expected_identity_id\":\"$ID\",\"identity_id\":null}" $B/api/v1/occurrences/$OCC/reassign | j "d['identity_id'][:8]"
curl -s -H "$H" $B/api/v1/sources/$SRC/unresolved-faces
```

Observed: confirm returns the occurrence unchanged; the wrong-view call `{"error":{"code":"OCCURRENCE_MOVED","message":"This
face now belongs to someone else. Reload and try again.","details":{"reason":"occurrence ... now belongs to another
identity than the one shown"},...}}`; the separate call returns the same occurrence under a **new** identity id
(`e4e0c016` where it had been `cf485fde` in that run) and the old identity keeps its other faces; and
`unresolved-faces` is `{"items":[]}`. Why can't you make an abstention by hand? The development profile embeds every
picture as an independent random vector (cosine near 0), far below the demo policy's "clearly new" ceiling of 0.5, so its
faces are always either matched or new, never "in between". The resolve flow is therefore proven by
`tests/integration/test_api_corrections.py` (planted perception that produces abstentions):

```bash
uv run pytest tests/integration/test_api_corrections.py -q
```

Expected: `20 passed` (observed).

## 5. Change it

Run on 2026-10-12: change the code string `"OCCURRENCE_MOVED"` in `corrections.py` to `"OCCURRENCE_GONE"` and run
`tests/integration/test_api_corrections.py`: it fails at `test_a_stale_view_is_refused_and_changes_nothing`. Error codes
are part of the contract (the front end switches on them; see `frontend/src/features/source/FaceCorrection.tsx`), so a
rename needs the front end and the tests to change in the same commit. Restore the file.

## 6. Break it on purpose

Send `reassign` with an `identity_id` that is not `ACTIVE` (merged away or forgotten): `404 IDENTITY_NOT_FOUND`. Confirm a
face whose source was permanently deleted: `404 OCCURRENCE_NOT_FOUND`. Resolve a representation that already has an
identity: `409 FACE_NOT_RESOLVABLE`. In all cases nothing is changed (checked inside the same transaction).

## 7. Exercises

1. What does `expected_identity_id` protect against?
2. How do you say "this face is someone new"?
3. After moving a face, does the vector index change? Why not?
4. What is `likely` in an unresolved face, and is it a decision?

**Answers**

1. Applying a correction to a face that has since moved to another identity in another window.
2. `reassign` with `identity_id: null` (or `resolve` with `null` for an unplaced face).
3. No; only ownership changed, and ownership is not part of the index (the index maps keys to vectors).
4. Up to three identities it resembled most with a similarity; a hint, recomputed live, never a decision.

## 8. Related files

- Previous: [people](people.md) · Next: [identity changes](identity-changes.md) · [Routes index](README.md)
- [Occurrences and evidence](../../domain/06-occurrences-and-evidence.md), [decisions in memory](../../recognition/04-decisions-in-memory.md)
- [`backend/app/identities/corrections.py`](../../../../../../backend/app/identities/corrections.py)
