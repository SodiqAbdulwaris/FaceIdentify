# M7 step 5: the Cameras screen, camera history and its deletion

- **Date:** 2026-11-12
- **Milestone / tracker IDs:** M7 step 5 · TST-071 (history), SEC-006 (deletion privacy, the camera half)
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(cameras): delete camera history for good`, `feat(api): add the camera routes and the session service`, `feat(frontend): add the Cameras screen, history and Camera on`, `docs: record M7 step 5`

## What changed

- `backend/app/cameras/service.py` (`CameraService`): configure a camera (a `CAMERA` Source and its device row), remove it (its history stays), start one session at a time on its own thread, stop it (its open encounters are recorded), report it (`STARTING`, `RUNNING`, `RECONNECTING`, `STOPPED`, `FAILED` with the reason's code; frames, dropped frames, open and recorded encounters) and give the **preview**: the newest frame with its faces outlined, encoded as a JPEG only when asked, held in memory only, never written. `Backend` creates it after the library opens (when processing is on) and stops a running session at shutdown; `ProcessingSettings.open_camera` lets a host plant a frame source (tests), else the device is read through the pinned ffmpeg.
- `backend/api/routes/cameras.py`: `GET /cameras/devices`, `POST /cameras` (201), `GET /cameras`, `GET /cameras/{id}`, `DELETE /cameras/{id}` (the configuration; `?history=true` also deletes all its history for good, through the existing permanent deletion of its Source), `POST /cameras/{id}/start` (202), `POST /cameras/{id}/stop` (202), `GET /cameras/{id}/status`, `GET /cameras/{id}/preview` (`image/jpeg`, `no-store`), `GET /cameras/{id}/faces/{observation_id}/crop` (a camera face's stored crop), `POST /cameras/{id}/history/delete`. Errors: `CAMERA_NOT_FOUND`, `CAMERA_BUSY`, `CAMERA_DISCONNECTED`, `MEDIA_TOOLS_UNAVAILABLE`, `PROCESSING_UNAVAILABLE`, `MEDIA_NOT_FOUND`. The camera's encounters and unplaced faces are read through the existing `/sources/{id}/occurrences` and `/sources/{id}/unresolved-faces`; an unresolved face gains `seen_at_ms` (when it was seen; None in an image) so history can be shown by day.
- `backend/app/cameras/history.py` (`DeleteCameraHistory`): one encounter, a selection, a UTC time range (a day) or everything, in the order of a Source's permanent deletion (M5 step 4c): intent (faces and their encounters `DELETED`, vectors queued for erasure, crops' deletion intent, identities bumped) in one transaction; then crop bytes removed and vectors erased (rows, index files, write-ahead log); then the rows removed, Evidence kept and detached from them, the log truncated. A locked file is reported and the next deletion carries it on. Refused while a session runs.
- Frontend: `features/cameras/` (`CamerasPage`: add a device, Start and Stop, status in plain words with what to do about a failure, the live preview, removal with or without history after asking; `CameraHistoryPage`: visits by day with the kept face and the person, unrecognised faces, delete a visit, a selection, a day or everything after asking; `CameraOn`: a "Camera on" indicator in the header of every screen while a session runs (C4); `ConfirmButton`). Camera events refresh the cameras and their history.
- Tests: `tests/integration/test_camera_history.py` (deleting one encounter removes it, its faces, vectors, index operations and the crop files on disk, keeps Evidence and the person; a time range; everything, then the camera still records; a locked file carried on by a repeat; refused while running; only a camera; two people in one frame), `tests/integration/test_api_cameras.py` (the routes over HTTP with a planted camera: configure, list, start, status, preview, refusals while running, stop, unplaced faces and crops, history deletion, removal with and without history, reconnecting, a crashing session, incomplete deletions, devices and missing tools, without processing; the real ffmpeg reporting a missing device), `frontend/src/features/cameras/CamerasPage.test.tsx`.

## Why

[M7 plan](../plans/M7_PLAN.md) step 5 and decisions C3, C4 and C9; product spec section 9 (deletion of an encounter, selected history, a day or range, all history of a camera).

## Decisions

> **Decision 2026-11-12 (delegated decision, M7 step 5):** removing a camera without its history marks its Source `UNAVAILABLE` and hides it from the camera list; its encounters and faces stay in the library (C9). Removing it with its history is the existing permanent deletion (recycle, then delete for good), which already handles a Source without an original.

> **Decision 2026-11-12 (delegated decision, M7 step 5):** history deletion is permanent and immediate with a confirmation in place, no Recycle bin (C9). Camera history is shown by local day; a day's deletion sends that day's UTC range.

> **Decision 2026-11-12 (delegated decision, M7 step 5):** the live preview and the session status are polled once a second while a session runs (and refreshed by `camera.*` events); the "Camera on" indicator checks every 5 seconds as a backstop to the events.

> **Decision 2026-11-12 (delegated decision, M7 step 5):** the camera list is not paginated (a household has a handful of cameras).

## Verification

Targeted (2026-11-12): camera history 8 passed, camera routes 18 passed; `history.py`, `service.py`, `routes/cameras.py` 100% covered; frontend 229 passed, typecheck clean, lint: no warning in the new files, build OK. The full backend gate is in the PR.

## Open issues / follow-ups

- A desktop end-to-end run of the Cameras screen with a scripted camera is not built: the development profile has no switch to plant a frame source. The route-level and screen tests cover the same paths.
- Faces deleted while their bytes could not be removed stay `DELETED` (invisible) until the next deletion of that camera's history or the next start's artifact recovery finishes them.
