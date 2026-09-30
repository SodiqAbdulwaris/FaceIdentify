# M2: Storage Manager, conservative cleanup

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (conservative cleanup of unreferenced managed artifacts; storage usage is its
  own PR)
- **Commits:** PR #20: `feat(sources): discover what references an artifact`,
  `feat(sources): clean up unreferenced managed artifacts`,
  `test(sources): add conservative cleanup tests`, `docs: record conservative cleanup`,
  `fix(sources): make cleanup stricter about age, keys and references`,
  `docs: record the conservative cleanup review`

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
- Tests: `tests/integration/test_storage_cleanup.py` (33).

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
- **References come from the schema, not from a list, and only foreign keys count.** A hand-kept list goes stale the first time a
  table gains an `artifacts.id` foreign key, and a stale list deletes bytes something still needs. A
  test pins the current six columns and requires a case for each, so a new reference fails the suite
  until it has been looked at.
- **The check is part of the deletion-intent `UPDATE`, not only of the listing.** An import's bytes
  are stored and made `AVAILABLE` *before* its Source commits, so a Source can reference an artifact
  after it was chosen. The intent is refused in the database in that case, and the artifact is
  reported as `skipped`. A test makes the window real.
- **The cutoff has no default.** It is the grace period that protects that window and the caller
  knows its own; choosing a number would be an unmeasured threshold. It is compared with when the
  artifact *became available*, so a long write cannot make a finished artifact look old; an artifact
  with no availability time is never collected (its creation time is when it was reserved); the
  comparison is strict, so an artifact exactly at the cutoff stays.
- **A reference made after the intent is the creator's to prevent.** The intent's `UPDATE` refuses
  an artifact that is referenced when it runs. A reference created to an artifact *already marked
  `DELETING`* cannot be stopped from here without database triggers, and does not need them:
  whatever creates a reference (the future import use case) must, in its own transaction, first check
  that the artifact is still `AVAILABLE`. SQLite has one writer, so that check and the intent are
  serialized and one of them loses cleanly. This contract is in the module docstring and in CONTEXT;
  nothing creates such references yet.
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
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 499 passed (33 new, 0 regressions in the 466
  before); `backend/` coverage 100%. The new file was run 5 times in a row before review and 5 after
  the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 13 (dropping the managed-mode or the
  AVAILABLE filter, the strict comparison, each of the two fall-backs of the availability time, the
  ordering, the reference condition in the listing and in the deletion intent, the intent
  guard being applied to every deletion, dropping the first or last referencing column, inverting
  the condition, and letting `ArtifactStateError` or `OSError` escape). Two survived at first (the
  reference condition in the listing alone, since the deletion-time guard still saved the data, and
  the ordering, since six artifacts were needed to make id order differ from age order); the
  assertions now require that a referenced artifact is never even chosen and use six artifacts. All
  13 are caught.

After the review, 5 more mutations (the key check before the intent, catching the unusable-key
error, the availability-time fallback, dropping the first or last referencing column), all caught.
One clause added in the fix, an explicit `IS NOT NULL`, is redundant (a NULL comparison is already
false in SQL), so no test can tell it from its absence; it was removed rather than kept untested.

## Independent review (Codex CLI, read-only, disposable worktree): five findings, addressed

| # | Finding | Resolution |
|---|---|---|
| P1 | A reference created after the `DELETING` intent commits can lose its bytes | **Not a trigger; a contract.** Whatever creates a reference must check in its own transaction that the artifact is still `AVAILABLE`; SQLite's single writer serializes that against the intent. Recorded in the module docstring, this entry and CONTEXT. Database triggers on six columns would be a schema change for a window that only a not-yet-written import use case can open |
| P1 | A null `available_at` falls back to an old `created_at`, defeating the grace period | Fixed: only a non-null `available_at` counts; such a row is never collected. The test is reversed |
| P2 | A malformed stored key raises after the intent is committed, stopping the batch and leaving the row `DELETING` | Fixed: `delete_managed_artifact` validates the key before committing the intent (a corrupt row is now refused without a state change, for every caller), and cleanup reports it as `skipped`. A test puts a corrupt key ahead of a good artifact |
| P2 | The "all references" claim covers only declared foreign keys | Fixed in the wording: the module and this entry say *declared foreign keys*, and state the rule that a reference that keeps bytes alive must be one. No other kind exists today |
| P2 | The race test exercises only `sources.original_artifact_id` | Fixed: it runs for every reference kind, committing the reference after the candidate was chosen |
| Doc | The PR number was missing | Fixed |

The reviewer found the intent, bytes, finalize structure conforms to API §§51-60 and persistence
§4.1, and did not run the tests.

## Open issues / follow-ups

- Storage usage (the last TST-025 item) follows.
- Wiring a cleanup call into the app (a scheduled or user-triggered action, with a chosen cutoff)
  belongs with the scheduler and settings work.
- **Hard-deleting the rows** of `DELETED` artifacts is not done: the rows are the audit trail and
  persistence §4.1 keeps them.
