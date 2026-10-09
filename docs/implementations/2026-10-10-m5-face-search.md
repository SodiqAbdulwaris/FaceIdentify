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

## Changes after the independent review

- Validation, reasoning and the response are built in **one read transaction** (`FaceQuery.search` takes the
  presenter), so a forget, delete or merge that commits later cannot leak into an answer; the index is opened
  under the coordinator's lock, so a pass cannot publish or clean up the generation being loaded.
- The body is counted as it arrives (the import limit; 8 KiB for the JSON form), a path is read through one
  handle and never past the limit (`413`), network (UNC/device) paths are refused, one search decodes and
  perceives at a time, and the request body forms are in the OpenAPI contract.
- A failed worker and an unusable index are plain `503`s (`PERCEPTION_UNAVAILABLE`,
  `SEARCH_INDEX_UNAVAILABLE`).
- The screen keeps the picture in the component (not the query cache), asks again when an event changes a
  face, a name or an image, hiding the old answer meanwhile, and announces progress and the number of
  faces in a polite status line.
- The no-write test now compares every row of every authoritative table and the hash of every library file;
  tests for several faces, a merged person, limits, unavailable states and concurrent searches were added.
- **Known limitation, not changed:** a query and a processing run share the perception worker. If a run
  crashes the worker while a query is still copying its output, the query fails with a retryable `503`
  (`PERCEPTION_UNAVAILABLE`); a lease covering execute-copy-release across both is a follow-up in the
  supervisor, not part of this step.

## Decisions (owner, 2026-10-10)

- **PDF queries are deferred.** Picture-only search is enough for M5. A future enhancement needs separate
  decisions about page selection, several faces, rendering, licensing and query behaviour; no renderer or
  dependency is added now.
- **A native Windows file picker is approved as a separate small PR after this one.** It keeps the browser
  file input, drop and paste, reuses this same query-only pipeline, adds no second backend path and saves
  no query image.
- **Real-model behaviour stays unverified until the step 8 gate.** The gate starts from the public-domain
  photo set; unverified identity labels are not ground truth.
- **Owner-controlled cleanup stays pending:** `local-models/state/indexes/f0fd4e92c8c8492097e2307e82000af9`
  is a leftover index directory from an earlier profile that agents must not delete (the owner removes it
  by hand).
- **R5 (label-review utility) stays pending** until the dataset and review requirements are agreed.

## For the owner (not blocking)

- Nothing blocks. PDF queries and the native file picker are decided above.
- **Similarity numbers are raw cosine values** until a calibration exists (the initial policy is
  abstain-only, so no match is ever accepted and every answer is `POSSIBLE_PEOPLE` or `UNKNOWN`). The screen
  says so.

## Tests

- `tests/integration/test_api_face_search.py` (19), on a real library with planted perception: a known face
  finds its person nearest first with similarity; a stranger is not named; no face; a search writes no row
  and no file (every table count and every library file compared before and after, repeated, from a path
  and from bytes); path and bytes give the same answer; unreadable, unsupported, corrupt and oversized
  pictures; forgotten, deleted and recycled people; perception and configuration failures; poor detection
  and an empty library; a person seen twice; and the same answer after restarting the application.
- `frontend/src/features/search/FaceSearch.test.tsx` (9).
- `tests/fixtures/api.py` gained `processing_app`, so a test can restart the application on one library.
