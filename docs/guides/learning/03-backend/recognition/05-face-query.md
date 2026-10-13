# Recognition 05 The face query

## 1. What this is and why it exists

"Who might this be?" asked of a photograph you do **not** want to add to the library. The face query runs the same pipeline as
processing (decode, detect, embed, retrieve, assess, decide) but entirely in memory and in read-only transactions: no source,
observation, representation, identity, evidence, job, run or file is created, so asking repeatedly can never grow or change
the memory. Even with automatic matching off, it still lists the nearest known people with their similarity, which is the
*assisted* recognition the owner chose (2026-10-08).

## 2. Where it lives

| Thing | Where |
|---|---|
| `FaceQuery` | `backend/app/recognition/face_query.py` |
| The route and its limits | [face-search routes](../api/routes/face-search.md) (`backend/api/routes/face_search.py`) |
| The screen | `frontend/src/features/search/FaceSearch.tsx` |
| Tests | `tests/integration/test_query_only_recognition.py` (13), `test_api_face_search.py` |

## 3. How it works

- Decode the picture with the same bounded decoder, find faces and embed them under the **current** processing configuration
  (so a policy file edit applies at once, [profiles](../architecture/04-profiles.md)).
- For each face: retrieve from the global index, revalidate in SQLite, assess, then ask the reasoner under the same policy.
  Nothing is written; the vectors and bytes are dropped when the call returns.
- The answer is per face: a box, the decision and its reason, and the nearest groups with similarities and the people they
  are linked to. The route limits concurrency (three at once, one decoding at a time) and refuses network paths.
- Because it is read-only, no `Evidence` explains a face query; it explains itself in its response.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_query_only_recognition.py tests/integration/test_api_face_search.py -q
```

Expected: `33 passed` (observed). The tests that matter: `test_a_query_creates_no_persistent_state`, `test_repeating_the_same_query_does_not_grow_memory` (in `test_query_only_recognition.py`) and `test_a_search_writes_nothing_and_repeating_it_changes_nothing` (in `test_api_face_search.py`). The same file also shows how a candidate that was merged away is resolved to its survivor (`test_resolves_a_merged_candidate_to_its_survivor`) and a forgotten or pending one is dropped. For the live
route (development profile, two nearly identical pictures), follow the curl walk-through in the [face-search lesson](../api/routes/face-search.md).

## 5. Change it

Adding a field to the answer is a route-schema change: add it in the response model, regenerate the contract
(`npm run generate:api`, [contract lesson](../api/03-openapi-and-contract.md)) and add a test. Never add a write to this path; the query-only test
exists to catch it.

## 6. Break it on purpose

Add an `INSERT` in a scratch edit anywhere in `face_query.py` (or open the unit of work for writing) and run
`test_query_only_recognition.py`: `test_a_query_creates_no_persistent_state` fails. Restore with `git restore`.

## 7. Exercises

1. What is the difference between processing a picture and face-searching it?
2. Why can a face search run when automatic matching is off?
3. What stops it from growing the library?

**Answers**

1. Processing stores and decides; a face search only reads and reports, then forgets the picture.
2. It offers candidates for a human to judge and does not commit a match.
3. Read-only transactions and no writes, enforced by tests that compare the memory before and after.

## 8. Related files

- Previous: [04](04-decisions-in-memory.md) · Up: [Recognition](README.md)
- [`backend/app/recognition/face_query.py`](../../../../../backend/app/recognition/face_query.py), [search route](../api/routes/search.md)
