# M7 step 1: camera source schema and spec text (revision 0012)

- **Date:** 2026-11-11
- **Milestone / tracker IDs:** M7 step 1 · TST-071 (the model half)
- **Status:** done (schema and spec only; capture, sessions and the routes follow in steps 2 to 6)
- **Commits:** PR (number recorded when merged): `feat(db): add camera sources in revision 0012`, `docs: record M7 step 1`

## What changed

- `backend/alembic/versions/0012_camera_sources.py`: `sources.kind` gains `CAMERA`;
  `sources.original_artifact_id` becomes nullable for a camera only
  (`ck_sources_original_unless_camera`: `(kind = 'CAMERA') = (original_artifact_id IS NULL)`); the new
  table `camera_source_metadata` (`source_id` primary key and FK, `CASCADE`; non-blank `device_name`;
  nullable, non-blank `device_path`); `jobs.type` gains `PROCESS_CAMERA_SESSION`. `sources` and `jobs`
  are rebuilt from frozen definitions (batch mode); every row is kept. Downgrade restores the earlier
  shape, guarded like every destructive downgrade, and a camera Source or camera job stops a forced one.
- Review follow-ups (Codex, PR #251): `ck_sources_camera_has_no_media` (a camera has no thumbnail or media facts); triggers `trg_camera_source_metadata_camera_only_insert` and `_update` refuse a device row on a Source that is not a camera; `require_media_source` makes the Source routes (recycle, restore, recheck, relink; detail and media already joined the original) answer `404 SOURCE_NOT_FOUND` for a camera; the OpenAPI document and frontend types regenerated (the job type enum).
- Models: `SourceKind.CAMERA`, `Source.original_artifact_id: UUID | None` with the CHECK,
  `JobType.PROCESS_CAMERA_SESSION`, `backend/app/cameras/models.py` (`CameraSourceMetadata`), registered
  in `backend/app/models.py`. One test narrowed a now-optional id (`test_execute_video_job.py`).
- Tests: `tests/integration/test_migration_0012.py` (a populated 0011 library keeps every row; each new
  rule refuses a violating row; the device row goes with its Source; downgrade on empty and populated
  libraries; camera rows stop a forced downgrade; offline SQL). The spec value-set and foreign-key
  tests list the additions; the head revision is `0012`. `ModelFactory.camera()`.
- Spec text (delegated decisions, below): PERSISTENCE_IMPLEMENTATION.md 4.2 and 15, API and
  Contracts.md 4, 24 and 33, ERD.md (`camera_source_metadata`), processing-architecture-v1.md 25.

## Why

[M7 plan](../plans/M7_PLAN.md) step 1 and decisions C1 to C10: a configured camera is a `CAMERA`
Source (product 5.4, FR-056 to FR-059); its device is the one thing stored about it; an encounter is a
`TRACK` occurrence, so no encounter tables.

## Decisions

All are the agent's under the owner's delegation of 2026-11-09 ("i'll leave the rest of the decisions
entirely to you"; spec text "Delegate to me"); the owner may reverse any.

> **Decision 2026-11-11 (delegated decision, M7 step 1):** the spec text the plan's step 1 asked for, recorded as dated notes in the four specs: the `CAMERA` kind and the nullable original for a camera only; `camera_source_metadata` as `source_id`, `device_name`, `device_path`; a session as one `PROCESS_CAMERA_SESSION` job with one run and a frozen snapshot holding `camera.sample_fps` 5, `camera.reconnect_timeout_seconds` 30 and `camera.encounter_gap_seconds` 5 (application defaults: no settings screen exists, as with the video sampling rate); encounters as `TRACK` occurrences accepted one closed encounter at a time while the session runs, every session's output staying authoritative (no supersession, no reprocessing of a camera); no session ever restarted automatically; the `cameras` route family, the five camera errors and the two `camera.*` events.

> **Decision 2026-11-11 (delegated decision, M7 step 1):** `device_path` stores DirectShow's alternative name (`@device_pnp_...`) beside the friendly name, because friendly names are not unique across drivers (plan section 7, "DirectShow naming"). The pinned `ffmpeg` lists both (checked on this machine 2026-11-11: one device, "Integrated Camera", with its alternative name; `ffmpeg -devices` lists `dshow`, which settles C1's open check).

> **Decision 2026-11-11 (delegated decision, M7 step 1):** the device row is deleted with its Source (`CASCADE`), unlike the derived tables (`RESTRICT`): it is part of the camera's configuration, not derived history. Removing a camera configuration (step 5) decides separately what happens to its history.

> **Decision 2026-11-11 (delegated decision, M7 step 1):** a camera Source is not listed by `GET /sources` (its reads join the original artifact, which a camera does not have): cameras are listed by `GET /cameras` (step 5).

## Verification

Targeted, 2026-11-11: `uv run pytest -q tests/integration/test_migration_0012.py tests/integration/test_migrations.py tests/integration/test_schema_contract.py tests/integration/test_core_models.py tests/integration/test_library_lifecycle.py`: all pass. `uv run mypy`: clean (334 files). The full backend gate is recorded in the PR.

## Open issues / follow-ups

Steps 2 to 7 of the plan. The settings keys stay application defaults until a settings screen exists.
