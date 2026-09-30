# M2: Storage Manager, conservative cleanup

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (conservative cleanup of unreferenced managed artifacts; storage usage is its
  own PR)
- **Commits:** PR (number added when opened): `feat(sources): discover what references an
  artifact`, `feat(sources): clean up unreferenced managed artifacts`,
  `test(sources): add conservative cleanup tests`, `docs: record conservative cleanup`

## What changed

- `backend/app/sources/artifact_references.py`: `artifact_reference_columns()` lists every foreign
  key, in any table, that points at `artifacts.id`, read from `Base.metadata`; and
  `unreferenced_artifacts()` is a SQL condition ("no row references this artifact") built from it.
  Today that is six columns: `sources.original_artifact_id`, `sources.thumbnail_artifact_id`,
  `observations.face_crop_artifact_id`, `model_exports.artifact_id`,
  `installed_model_exports.artifact_id`, `runtime_package_installations.artifact_id`.
- `backend/app/sources/artifact_storage.py`: `transition_artifact` takes an optional `extra_where`;
  `request_artifact_deletion` and `delete_managed_artifact` take `only_if_unreferenced`, which adds
  the condition to the deletion-intent `UPDATE` itself.
- `backend/app/sources/storage_cleanup.py`: `find_unreferenced_artifacts(session, *, older_than)`
  and `cleanup_unreferenced_artifacts(session_factory, store, *, older_than, clock)`, returning a
  `CleanupReport` (`deleted`, `skipped`, `failed`). Each artifact goes through the existing crash-safe
  protocol (intent, bytes, finalize).
- Tests: `tests/integration/test_storage_cleanup.py` (26).

## Why

TST-025 lists conservative cleanup; API and Contracts §51 gives it to the Storage Manager; the
previous entry (managed core, review finding M2) left one case for exactly this task: an
`AVAILABLE` managed artifact that nothing references, which appears when an import's bytes were
stored and its final commit then failed and startup recovery completed the artifact.

## Decisions

- **What is collected: only `AVAILABLE` managed artifacts that nothing references, older than a
  caller-supplied cutoff.** Everything else is out of reach by construction: referenced originals
  (the user's files, §52), any other state, and anything a row points at, including a recycled
  Source's original and thumbnail (so a restore never needs reprocessing).
- **References come from the schema, not from a list.** A hand-kept list goes stale the first time a
  table gains an `artifacts.id` foreign key, and a stale list deletes bytes something still needs. A
  test pins the current six columns and requires a case for each, so a new reference fails the suite
  until it has been looked at.
- **The check is part of the deletion-intent `UPDATE`, not only of the listing.** An import's bytes
  are stored and made `AVAILABLE` *before* its Source commits, so a Source can reference an artifact
  after it was chosen. The intent is refused in the database in that case, and the artifact is
  reported as `skipped`. A test makes the window real.
- **The cutoff has no default.** It is the grace period that protects that window and the caller
  knows its own; choosing a number would be an unmeasured threshold. It is compared with when the
  artifact *became available* (falling back to when it was created), so a long write cannot make a
  finished artifact look old; the comparison is strict, so an artifact exactly at the cutoff stays.
- **Stray files on disk are never deleted.** `scan_storage` reports them. A file no row owns may just
  be a file whose row was lost (a database restored from an older backup): then it is the only copy.
  Keeping a stray file costs disk space; deleting it can cost the data. They stay a report.
- **Tolerant, like recovery.** A byte-deletion failure leaves the artifact `DELETE_FAILED` (the
  existing protocol; startup recovery retries it, and a test shows it finishing the job) and does not
  stop the rest.
- **Not here:** deleting *referenced* derived data such as face crops (`observations` may null the
  link, "cleanup may remove a derivative crop", observations model comment), cleaning caches and
  runtime artifacts (§16.7's other tiers), abandoned workspaces (`WorkspaceManager.remove_orphans`),
  and what to do with a `MISSING` row that has no bytes. Each needs its own decision and call site.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 492 passed (26 new, 0 regressions in the 466
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 26 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 13 (dropping the managed-mode or the
  AVAILABLE filter, the strict comparison, each of the two fall-backs of the availability time, the
  ordering, the reference condition in the listing and in the deletion intent, the intent
  guard being applied to every deletion, dropping the first or last referencing column, inverting
  the condition, and letting `ArtifactStateError` or `OSError` escape). Two survived at first (the
  reference condition in the listing alone, since the deletion-time guard still saved the data, and
  the ordering, since six artifacts were needed to make id order differ from age order); the
  assertions now require that a referenced artifact is never even chosen and use six artifacts. All
  13 are caught.

## Open issues / follow-ups

- Storage usage (the last TST-025 item) follows.
- Wiring a cleanup call into the app (a scheduled or user-triggered action, with a chosen cutoff)
  belongs with the scheduler and settings work.
- **Hard-deleting the rows** of `DELETED` artifacts is not done: the rows are the audit trail and
  persistence §4.1 keeps them.
