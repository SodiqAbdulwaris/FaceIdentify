# M2: Storage Manager, temporary workspaces

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (temporary workspaces; recycle/restore, usage and cleanup follow)
- **Commits:** PR (number added when opened): `feat(storage): allocate and clean up temporary job
  workspaces`, `test(storage): add temporary workspace tests`, `docs: record temporary workspaces`

## What changed

- `backend/infrastructure/storage/workspaces.py`: `WorkspaceManager(roots)`.
  - `allocate(job_id)` creates `<local state>/temp/jobs/<job id hex>/` with `decode/`, `frames/`,
    `crops/` and `intermediate/` (IMPLEMENTATION_ARCHITECTURE §16.5) and returns it. Idempotent: a
    retried or resumed job gets its existing workspace back, files included.
  - `release(job_id)` removes a workspace and everything in it. Idempotent. It does not follow a link
    out of the workspace, and refuses a workspace that is itself a link.
  - `existing()` lists the job ids that have a workspace.
  - `remove_orphans(live_jobs)` removes every workspace whose job is not in `live_jobs` and returns a
    `WorkspaceCleanup` (`removed`, `kept`, `unowned`, `failed`). One workspace that cannot be removed
    is reported and does not stop the rest.
- Tests: `tests/integration/test_workspaces.py` (14).

## Why

TST-025 lists temporary workspaces; API and Contracts §51 gives them to the Storage Manager; the
architecture (§16.5) says subsystems may write temporary computational files "only within
controlled allocated workspaces"; persistence §28: "orphan processing temp workspace → remove only
application-owned workspace after verifying no live run needs it".

## Decisions

- **Machine-local, not in the library.** Workspaces hold disposable, reconstructable files, so they
  live under `%LOCALAPPDATA%/<App>/temp` (tech-stack §15), never in the library that is backed up or
  moved. Nothing authoritative is ever written to one.
- **The manager deletes only what it named.** A directory is a workspace only if its name is exactly
  32 lower-case hex digits and it is a real directory. Files, other names, upper-case names and
  links under `temp/jobs/` are reported as `unowned` and left alone (recovery's rule for staging
  files, applied here).
- **Links are never followed.** A junction inside a workspace is removed as a link, not emptied
  (`shutil.rmtree` on Python 3.12 handles junctions this way; tests prove a folder outside the roots
  keeps its files); a workspace that is itself a link is refused.
- **Liveness is the caller's.** `remove_orphans` takes the set of live job ids. Which jobs are live
  needs the `jobs` table and the recovery ordering, which belong to startup recovery (TST-030). This
  module does not touch the database.
- **A removal failure is reported, not fatal.** A locked file (antivirus, an ML worker that has not
  released it) leaves that workspace in `failed`, and the next cleanup retries it.
- **No size limits or quotas.** The specs give none; disk pressure is a Storage Manager
  responsibility of usage reporting (a later PR) and the scheduler (M6).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 433 passed (14 new, 0 regressions in the 419
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 14 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 14 (dropping the link refusal on
  release or checking only symlinks, releasing a workspace that is absent, dropping the name pattern
  in `existing` or in cleanup, not excluding links, ignoring live jobs, catching only
  `FileNotFoundError`, `ignore_errors` hiding a failure, requiring the subdirectories not to exist,
  a case-insensitive name, and the two missing-root shortcuts). All 14 caught.
- **Not verified:** a workspace on a different drive from the library (irrelevant here: nothing is
  renamed across roots), and behaviour under an antivirus scan in progress, other than through an
  open handle.

## Open issues / follow-ups

- Wiring `remove_orphans` into startup, with the live job ids from the database, is TST-030.
- Nothing yet allocates a workspace: the first user is the M3 image-processing pipeline.
