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
- `LibraryLock` has no explicit unlock: closing the file releases the lock on both platforms (a mutation that removed the
  explicit unlock survived because it is redundant, so it was deleted).
- A test of the lock found that `sys.executable` is the virtual environment's launcher on Windows, which starts the real
  interpreter as a child: killing only the launcher left the lock held. The kill test therefore kills the process tree
  (`taskkill /F /T`). A real backend started by the shell must likewise be stopped as a tree.

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1107 passed, backend coverage 100%.
  16 mutations (the blocking lock variant is caught by a prompt-refusal assertion; the order of the sources, each
  validation, the blank rule, the default, the environment precedence in Alembic, the folder creation...), each shown to fail
  a test and restored byte-identical. The cross-process tests ran several times without a failure.
- **Not verified:** the lock on a network share or removable drive, and on a non-Windows platform (the suite runs on Windows).

## Open issues / follow-ups

- Issue #33: call these, then migrations and `recover_on_startup`, from the lifecycle; process-kill tests.
- The shell's persisted setting and first-run selection (desktop milestone).
