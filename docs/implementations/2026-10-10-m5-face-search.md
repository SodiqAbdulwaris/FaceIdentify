# M5 step 5b: face search

- **Date:** 2026-10-10
- **Milestone / tracker IDs:** M5 step 5b; TST-056
- **Status:** done; assisted cross-source recognition and the M5 gate (step 8) follow
- **Commits:** PR to be recorded when merged

## What changed

- **Use case** `backend/app/recognition/face_query.py` (`FaceQuery`): decode the picture, resolve the
  *current* processing configuration (the same `request_for` + `resolve` a processing run freezes), plan and
  call perception (detect, then represent), look every face up in the global index with the same
  `RecognitionService` a run uses, let SQLite revalidate each candidate, and judge the shortlist with the
  policy's `IdentityReasoner`. Everything runs in memory and in read-only transactions: no Source,
  Observation, Representation, Identity, Evidence, job, run or file is made (API section 12.2), and a
  repeat changes nothing.
- **Route** `POST /api/v1/search/face` (`backend/api/routes/face_search.py`). The picture is either the
  request body itself (any image content type) or JSON `{"path": "..."}` naming a file on this computer
  (read once, never copied). Limits are the import limits (bytes and pixels). One answer **per face found**:
  box, detection score, `status` (`IDENTITY_ANSWER` only if the policy accepts a match, else
  `POSSIBLE_PEOPLE` or `UNKNOWN`), the policy's `reason`, `possible_people` (identity summary, best cosine
  similarity, number of matching faces) and `retrieval_complete`. `ranking` names the plan and the
  policy version; the similarity is labelled `COSINE_UNCALIBRATED`, a score and not a probability. A
  picture with no face answers `200` with an empty list.
- **Who can be found.** Exactly the identities recognition can reach: forgotten identities (vectors
  erased), permanently deleted images and merged-away identities never appear; images in the Recycle
  bin still do (recognition memory survives recycling, identity model section 39).
- **Errors:** `400 QUERY_IMAGE_UNREADABLE`, `413 MEDIA_TOO_LARGE`, `415 MEDIA_FORMAT_UNSUPPORTED`,
  `422 MEDIA_CORRUPT`, `503 PROCESSING_UNAVAILABLE`, `503 PERCEPTION_UNAVAILABLE` (retryable).
- **Front end.** The Search screen has a "Search with a picture" box: choose a file, drop one on the box or
  paste one (a screenshot, a copied image). Unsupported types are refused before anything is sent. Each
  face is shown cropped from the picture with its possible people (name or label, similarity, matching
  faces, images), each linking to the person's page. Nothing is cached or saved.

## Owner decisions applied (2026-10-10)

Input may be a path, an upload or an attached/pasted picture; the answer is given for each face, grouped by
face; people are shown as "Possible people" with their similarity.

## For the owner (not blocking)

- **PDF queries are not built.** The owner said to try PDFs "if necessary". Reading a PDF needs a renderer (a
  new dependency and licence) and a rule for which page and which faces; face search over a picture does not
  need it, so it was left out (scope rule). Say if you want it.
- **The desktop app's native file picker is not used**: the web file input gives the app the picture's
  bytes, so the path form of the API is for scripts and the future. Say if a native picker is wanted.
- **Similarity numbers are raw cosine values** until a calibration exists (the initial policy is
  abstain-only, so no match is ever accepted and every answer is `POSSIBLE_PEOPLE` or `UNKNOWN`). The screen
  says so.

## Tests

- `tests/integration/test_api_face_search.py` (12), on a real library with planted perception: a known face
  finds its person nearest first with similarity; a stranger is not named; no face; a search writes no row
  and no file (every table count and every library file compared before and after, repeated, from a path
  and from bytes); path and bytes give the same answer; unreadable, unsupported, corrupt and oversized
  pictures; forgotten, deleted and recycled people; perception and configuration failures; poor detection
  and an empty library; a person seen twice; and the same answer after restarting the application.
- `frontend/src/features/search/FaceSearch.test.tsx` (7).
- `tests/fixtures/api.py` gained `processing_app`, so a test can restart the application on one library.
