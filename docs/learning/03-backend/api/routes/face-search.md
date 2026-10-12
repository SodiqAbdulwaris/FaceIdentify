# Routes: face search (`backend/api/routes/face_search.py`)

## 1. What this is and why it exists

"Who might be in this photograph?" without adding the photograph to the library. `POST /search/face` takes a picture,
finds its faces, looks each one up in the memory, and answers, **per face**, who the nearest known people are. It is a
**query, never an ingest**: nothing is saved (no Source, Observation, Representation, Identity, Evidence, job, run or
file), so repeating a search cannot grow the library, and the picture's bytes and vectors are dropped when the call
returns. It is independent of matching thresholds in one respect: even when automatic matching is switched off, it still
**offers possible people with their similarity** for you to judge. This is the *assisted* recognition the owner chose
(2026-10-08).

## 2. Where it lives

| Thing | Where |
|---|---|
| The route | `search_face` in `backend/api/routes/face_search.py` (the only `async def` route) |
| The logic | `FaceQuery` in `backend/app/recognition/face_query.py` (same retrieval, assessment and reasoner as processing, in memory and read-only transactions) |
| Limits | `Backend.face_search_slots` (3 at once) and `face_search_gate` (one decodes and perceives at a time) in `backend/api/startup.py` |
| The screen | `frontend/src/features/search/FaceSearch.tsx` |
| Tests | `tests/integration/test_api_face_search.py`, `test_query_only_recognition.py` |

## 3. How it works

**Request.** Either the image bytes as the body (`Content-Type: image/png`, `image/jpeg`, ... or
`application/octet-stream`), or JSON `{"path": "<a file on this computer>"}`: read once, never copied. A network path
(UNC or device, anything starting with two slashes or backslashes) is refused, because it could make this computer reach
out and authenticate to another one. A JSON body can be at most 8192 bytes; an image body at most the media limit (512 MiB
provisional). The body is counted as it streams, so nothing over the limit is kept.

**Answer.**

```json
{"faces": [{"index": 0, "bounding_box": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6}, "detection_score": 0.9,
            "status": "IDENTITY_ANSWER", "reason": "MATCHED",
            "identity_answer": { ...IdentitySummary... },
            "possible_people": [{"identity": { ...IdentitySummary... }, "similarity": 1.0, "matching_faces": 2}],
            "retrieval_complete": true}],
 "ranking": {"plan": "FACE_QUERY", "policy_version": "development-uncalibrated-v1", "similarity": "COSINE_UNCALIBRATED"}}
```

- `status`: **`IDENTITY_ANSWER`** when the current policy would accept a match (then `identity_answer` is set);
  **`POSSIBLE_PEOPLE`** when candidates exist but the policy does not accept one; **`UNKNOWN`** when nobody resembles it.
  `reason` is the reasoner's reason (`MATCHED`, `NOT_SIMILAR`, `UNCERTAIN_SIMILARITY`, `AMBIGUOUS_CANDIDATES`, ...).
- `possible_people` is each candidate identity with its best `similarity` (a cosine similarity, **not a probability**) and
  how many of its remembered faces matched.
- `retrieval_complete: false` means the index could not be trusted to hold the nearest faces (it was catching up).
- A picture with no faces is a successful empty `faces` list.
- Errors: `415 MEDIA_FORMAT_UNSUPPORTED`, `422 MEDIA_CORRUPT`, `413 MEDIA_TOO_LARGE`, `400 QUERY_IMAGE_UNREADABLE` (a path
  that cannot be read, or a network path), `429 FACE_SEARCH_BUSY` (retryable; more than three at once), `503
  PROCESSING_UNAVAILABLE` (no configuration, for example the real profile with no model package), `503
  PERCEPTION_UNAVAILABLE` (retryable; the worker failed), `503 SEARCH_INDEX_UNAVAILABLE`.

## 4. Try it

**Works with no models. Verified 2026-10-12** on the development profile (variables as in [call the API](../01-call-the-api.md);
`$P` the folder with the pictures).

```bash
curl -s -X POST -H "$H" -H "Content-Type: image/png" --data-binary @$P/red.png $B/api/v1/search/face \
  | j "[(f['status'], f['reason'], [(round(p['similarity'], 3), p['matching_faces']) for p in f['possible_people']]) for f in d['faces']]"
curl -s -X POST -H "$H" -H "Content-Type: application/json" -d "{\"path\":\"$P/green.png\"}" $B/api/v1/search/face \
  | j "[(f['status'], f['reason']) for f in d['faces']]"
```

Observed: for a picture already in the library `[('IDENTITY_ANSWER', 'MATCHED', [(1.0, 2), (0.208, 1)])]` (its own identity
with two identical faces at similarity 1.0, the other identity at 0.208); for a different, never-seen picture the answer
was `POSSIBLE_PEOPLE` with reason `NOT_SIMILAR` and a low similarity (about -0.095 in one run, 0.208 in another, whichever
identity is nearest: with the development profile's random vectors a stranger scores near 0). Errors observed: a text
file `MEDIA_FORMAT_UNSUPPORTED`; a path that does not exist, and a UNC path, both `QUERY_IMAGE_UNREADABLE`. **Nothing is
saved**: `GET /search?q=red&types=sources` showed `coverage {'sources': 6, 'processed': 5, 'not_processed': 1}` before and
after three face searches. Note the status names: the development profile's demo policy *can* accept a match; with the real
profile's abstain-only policy, `IDENTITY_ANSWER` never occurs and you always get `POSSIBLE_PEOPLE` or `UNKNOWN`.

*Needs the local models* for real faces: the same calls on a real-profile backend (unverified here: no model files in
the writing environment); the tests prove the shapes with planted perception.

## 5. Change it

Run on 2026-10-12: change `JSON_BODY_LIMIT = 8192` to `10` and run `tests/integration/test_api_face_search.py`: it fails at
`test_a_known_face_finds_its_person_and_shows_the_similarity` (the path body is longer than 10 bytes). Restore the file.
The other knob, `SEARCH_SHORTLIST = 50` (how many nearest faces a search looks at, so several people can be ranked,
against the small shortlist processing uses to judge one match), is an agent decision (M5 step 8): change it only with
evidence from the assisted-recognition gate ([evaluation](../../../06-evaluation-and-operations/03-assisted-gate-and-open-set.md)).

## 6. Break it on purpose

Send four searches at once: the fourth gets `429 FACE_SEARCH_BUSY` while three are in flight (`Backend.face_search_slots`,
`FACE_SEARCH_SLOTS = 3`); it is retryable. Search with a path that is a folder: `QUERY_IMAGE_UNREADABLE`. Search with a
huge-dimension picture: `413 MEDIA_TOO_LARGE`. None of these writes anything either.

## 7. Exercises

1. Why is face search "a query, never an ingest", and how can you check that?
2. What is the difference between `identity_answer` and `possible_people`?
3. Why are UNC paths refused?
4. What does `retrieval_complete: false` tell you?

**Answers**

1. It creates no rows or files; the coverage counts (or `select count(*)` on any table) are unchanged by any number of
   searches.
2. `identity_answer` is set only when the policy would accept a match; `possible_people` lists the nearest known people with
   their similarity whether or not the policy accepts one.
3. A network path could make this computer connect and authenticate to another machine.
4. The index could not be trusted to contain the nearest faces (it was catching up), so the shortlist may be incomplete.

## 8. Related files

- Previous: [search](search.md) · [Routes index](README.md)
- [Face query](../../recognition/05-face-query.md), [the decision policy](../../recognition/03-decision-policy.md)
- [`backend/api/routes/face_search.py`](../../../../../backend/api/routes/face_search.py), [`backend/app/recognition/face_query.py`](../../../../../backend/app/recognition/face_query.py)
