# M7 step 6: search with the camera

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M7 step 6 · TST-071, TST-057A (regression: face search unchanged)
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(cameras): search with the face in front of a camera`, `docs: record M7 step 6`

## What changed

- `POST /cameras/{id}/search`: one picture from the camera is searched exactly as an uploaded picture is (`search_picture`, the face search core now shared by both routes), in the worker's interactive class, under the same three-search limit (`429 FACE_SEARCH_BUSY`). Nothing is stored and the picture is not kept: it exists only as an in-memory PNG for the length of the request.
- `CameraService.capture`: while the camera's session runs, its newest frame (the device cannot be opened twice); otherwise the device is opened, one frame read (10 s at most) and the device closed again. Errors: `CAMERA_NOT_FOUND` (404), `CAMERA_IN_USE` (409), `CAMERA_ACCESS_DENIED` (403), `CAMERA_DISCONNECTED` (503).
- Frontend: "Search with this camera" on each camera, showing the answers with the same face card as the picture search (`Face`, now exported).
- Tests: in `tests/integration/test_api_cameras.py` (a search stores nothing and closes the device; during a session it uses the newest frame without reopening; after a session it opens the device again; each camera error; the shared search limit) and `CamerasPage.test.tsx`. The existing face search tests pass unchanged (`tests/integration/test_api_face_search.py`).

## Why

[M7 plan](../plans/M7_PLAN.md) step 6 and C10; product spec 10.4 (search the library with a face presented to a configured camera); query is not ingest (API 2.1).

## Decisions

> **Decision 2026-11-12 (delegated decision, M7 step 6):** the captured picture is not shown back (it is not kept), so the answer's face tile is blank; the answer itself (recognised, possible people, unknown) is the picture search's.

## Verification

Targeted (2026-11-12): camera routes and face search 234 passed (with the contract tests); frontend camera and search tests 34 passed; typecheck clean. The full backend gate is in the PR.
