# M2: Storage Manager, temporary workspaces

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (temporary workspaces; recycle/restore, usage and cleanup follow)
- **Commits:** PR #17: `feat(storage): allocate and clean up temporary job workspaces`,
  `test(storage): add temporary workspace tests`, `docs: record temporary workspaces`,
  `fix(storage): harden workspace ownership and link handling`, `docs: record the workspace review`

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
- Tests: `tests/integration/test_workspaces.py` (22).
- After review: an ownership marker (`.faceidentify-workspace`) written on allocation and required
  for a directory to count as a workspace; reparse points of every kind refused via `lstat`
  attributes; `allocate` refuses a link or a directory with someone else's files instead of writing
  through or into it; read-only files no longer keep a workspace alive (`WorkspaceError` replaces the
  earlier `ValueError`).

## Why

TST-025 lists temporary workspaces; API and Contracts §51 gives them to the Storage Manager; the
architecture (§16.5) says subsystems may write temporary computational files "only within
controlled allocated workspaces"; persistence §28: "orphan processing temp workspace → remove only
application-owned workspace after verifying no live run needs it".

## Decisions

- **Machine-local, not in the library.** Workspaces hold disposable, reconstructable files, so they
  live under `%LOCALAPPDATA%/<App>/temp` (tech-stack §15), never in the library that is backed up or
  moved. Nothing authoritative is ever written to one.
- **The manager deletes only what it made.** A directory is a workspace only if its name is exactly
  32 lower-case hex digits, it is a real directory (not a link, junction, mount point or any other
  reparse point) and it carries the ownership marker written on allocation. Files, other names,
  upper-case names, links and unmarked directories under `temp/jobs/` are reported as `unowned` and
  left alone (recovery's rule for staging files, applied here). An existing *empty* directory of the
  right name is adopted by `allocate` (a crash between creating and marking it); one with someone
  else's files is refused.
- **Links are never followed.** A junction inside a workspace is removed as a link, not emptied
  (`shutil.rmtree` on Python 3.12 handles junctions this way; tests prove a folder outside the roots
  keeps its files); a workspace that is itself a link is refused.
- **Liveness is the caller's, and read once.** `remove_orphans` takes the set of live job ids, which
  needs the `jobs` table and the recovery ordering, so this module does not touch the database. It
  has the same precondition as `recover_artifacts`: it runs at startup before any worker allocates or
  uses a workspace. Durable liveness and per-job coordination belong to startup recovery (TST-030).
- **A removal failure is reported, not fatal.** A locked file (antivirus, an ML worker that has not
  released it) leaves that workspace in `failed`, and the next cleanup retries it.
- **No size limits or quotas.** The specs give none; disk pressure is a Storage Manager
  responsibility of usage reporting (a later PR) and the scheduler (M6).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 441 passed (22 new, 0 regressions in the 419
  before); `backend/` coverage 100%. The new file was run 5 times in a row before review and 5 after
  the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 14 (dropping the link refusal on
  release or checking only symlinks, releasing a workspace that is absent, dropping the name pattern
  in `existing` or in cleanup, not excluding links, ignoring live jobs, catching only
  `FileNotFoundError`, `ignore_errors` hiding a failure, requiring the subdirectories not to exist,
  a case-insensitive name, and the two missing-root shortcuts). All 14 caught.
- **Not verified:** a workspace on a different drive from the library (irrelevant here: nothing is
  renamed across roots), and behaviour under an antivirus scan in progress, other than through an
  open handle.

After the review, 14 more valid mutations on the hardened guards. Nine were caught at once. Three
**survived** and were real gaps, now closed by tests and re-checked: the fail-closed answer when an
entry cannot be examined, cleanup not clearing a read-only file, and the "in-use directory is
reported, not forced" branch (found through coverage). One mutation was invalid (it changed
nothing) and was redone. Two survivors are left and judged unobservable: skipping the
`isinstance(error, PermissionError)` test, or the plain-file test, in the read-only hook. A locked
file raises again on its retry either way, and the plain-file test only matters if removing a link
ever raised, which would otherwise `chmod` the link's target.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| C1 (critical) | Check-then-delete is a TOCTOU: a workspace swapped for a link between the check and `rmtree` is followed; needs a handle-based deleter | **Not changed, recorded as a ceiling** (`ponytail:` in the module). `temp/jobs/` is machine-local and writable only by the current user, who can already do anything this process can, so a hostile swap is not in the threat model. A handle-based deleter is large Windows-specific code for no protection. Revisit if workspaces ever move where other users can write. Links *inside* a workspace are never followed (tested) |
| H1 (high) | `allocate` follows a pre-existing junction and creates directories in its target | Fixed: a link or other reparse point is refused (`WorkspaceError`), and a test proves the target is untouched |
| H2 (high) | Only symlinks and junctions are excluded; mount points and cloud placeholders are also reparse points | Fixed: `_is_plain_directory` uses `lstat` and rejects any reparse-point attribute. Tested with a junction (a real reparse point); mount points and cloud placeholders cannot be created without privileges or a cloud client, so they are covered by the same attribute check but not by their own test |
| M1 (medium) | `live_jobs` is a stale snapshot; a job may become live after it was read | Documented as a precondition, the same as `recover_artifacts`: run at startup before workers allocate. Durable liveness and per-job coordination belong to startup recovery (TST-030) |
| M2 (medium) | A UUID-named directory is owned by name alone | Fixed: an ownership marker is required; unmarked directories are reported as `unowned`, and `allocate` refuses one with foreign files |
| L1 (low) | Read-only Windows files leak temp storage | Fixed: read-only files are cleared and retried; a locked file still fails and is reported |
| L2 (low) | The implementation log still says the PR number is pending | Fixed |

The reviewer found the layout and subdirectories conform to Architecture §16.5 and API §51, and did
not run the suite.

## Open issues / follow-ups

- Wiring `remove_orphans` into startup, with the live job ids from the database, is TST-030.
- Nothing yet allocates a workspace: the first user is the M3 image-processing pipeline.
