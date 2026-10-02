# M2: the library root and the library lock

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M2 · TST-030; GitHub issues #36 (Q17) and #39 (Q23)
- **Status:** done for the backend side; the lifecycle that calls them is the next change (issue #33)
- **Commits:** PR #63: `feat(storage): resolve the library root and lock the library`, `docs: record the library root and lock`

## What changed

- `backend/infrastructure/storage/library_root.py`: `resolve_library_root(explicit, environ, persisted)` (explicit, then
  `FACEIDENTIFY_LIBRARY_ROOT`, then the persisted setting the shell passes in; nothing else, no default),
  `validate_library_root` (absolute; an existing directory, or a new one inside an existing folder; a file or a path whose
  parents do not exist is refused) and `resolve_local_state_root` (explicit, `FACEIDENTIFY_LOCAL_STATE_ROOT`, or
  `%LOCALAPPDATA%/FaceIdentify`). `LibraryNotSelectedError` is the first-run signal.
- `backend/infrastructure/storage/library_lock.py`: `LibraryLock(root)` takes an exclusive, non-blocking operating-system lock
  on `<root>/database/.lock` (`msvcrt.locking` on Windows, `flock` elsewhere) and holds it until `release()` (closing the
  file); a second holder gets `LibraryLockedError`, immediately. Not reentrant. A crash or kill frees it.
- `validate_distinct_roots(library, local_state)`: the two roots must be different folders, neither inside the other
  (canonical comparison); the lifecycle will call it.
- `layout.database_path_for(root)` is the one definition of the database path; `StorageRoots.database_path` uses it.
- `backend/alembic/env.py`: the database path is `config.attributes["database_path"]`, else `<FACEIDENTIFY_LIBRARY_ROOT>/
  database/library.db` (the folder is created), else the deprecated `FACEIDENTIFY_DATABASE_PATH`, else an error naming the
  root variable. Nothing is guessed.
- Spec note on persistence section 28, CONTEXT questions 17 and 23, tracker TST-030.

## Why

The owner decided (2026-10-01) that the shell owns library selection and the backend receives one resolved root, and that a
library-lifetime lock is taken after that and before migrations and recovery.

## Decisions

- The persisted setting itself (its file and folder) is the desktop shell's; the backend only accepts the value. Nothing here
  reads or writes it.
- An existing-but-not-yet-initialised folder is a valid root (first run creates the layout); a nonexistent root is valid
  only directly inside an existing folder, so a typo is refused instead of creating a deep tree.
- The deprecated `FACEIDENTIFY_DATABASE_PATH` still works (existing scripts and tests); nothing in the application reads it.
- `LibraryLock.release` unlocks explicitly and then closes. (I first deleted the unlock as redundant because a mutation that
  removed it survived; the review pointed out that the moment of release after a bare close is the operating system's, so a
  prompt restart could be refused. A test now pins the order: unlock while the file is still open.) Only an `EACCES`-style
  failure is reported as "held"; any other `OSError` surfaces as itself, and any other exception closes the file.
- A test of the lock found that `sys.executable` is the virtual environment's launcher on Windows, which starts the real
  interpreter as a child: killing only the launcher left the lock held. The kill test therefore kills the process tree
  (`taskkill /F /T`). A real backend started by the shell must likewise be stopped as a tree.

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1126 passed, backend coverage 100%.
  31 mutations (the blocking lock variant is caught by a prompt-refusal assertion; the order of the sources, each
  validation, the blank rule, the default, the environment precedence in Alembic, the folder creation...), each shown to fail
  a test and restored byte-identical. The cross-process tests ran several times without a failure.
- **Review** (Explore subagent; Codex over its limit until 2026-10-03), posted on PR 63: no blocker, three major. Fixed:
  Alembic's root path now goes through `validate_library_root` (it had bypassed it and would have created a typo'd path several
  levels deep); a blank or relative explicit value is refused instead of silently falling through to a lower source (a
  caller's unusable value is never replaced); the explicit unlock is back; the lock validates its root and creates nothing for a
  typo; only genuine "held" errors are reported as held and a leak on any exception path is closed; `realpath` replaces
  `normpath` (a link is followed as the platform does); the two roots cannot be equal or nested; the cross-process tests have
  start-up and kill timeouts, kill the whole process tree without failing on an already-gone one, and poll briefly for the
  operating system's release; the vacuous "nothing is guessed" test now moves the working directory and `LOCALAPPDATA` to
  where a guess would land; the stale `alembic.ini`/README/CONTEXT text. Answered: the Alembic command line does not take the
  lock (stated in the README and the lock's docstring; the lifecycle migrates under it); the first commit is above the
  ~400-line guide (root and lock are one decision pair with their tests); re-acquiring the same object is a
  `LibraryLockedError` because it is the same situation seen from this process; the tracker row stays one cell like its
  neighbours.
- **Not verified:** the lock on a network share or removable drive, and on a non-Windows platform (the suite runs on Windows).

## Open issues / follow-ups

- Issue #33: call these, then migrations and `recover_on_startup`, from the lifecycle; process-kill tests.
- The shell's persisted setting and first-run selection (desktop milestone).
