# M5: installation records follow the disk (issue 80)

- **Date:** 2026-10-08
- **Milestone / tracker IDs:** M5 track R; issue #80; TST-038, TST-039 (catalog truth under the real path)
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- **`mark_missing_installations(session)`** (`backend/app/runtime/registration.py`) moves every
  `INSTALLED` package-installation or model-export record to `MISSING` when its file is no longer on
  this machine, or when its artifact is no longer `AVAILABLE` (the startup check already found it
  gone). By existence alone: one `stat` per record, no file read. A file that exists but cannot be
  examined (permission, an unreachable drive) is left alone, because that is not evidence it is gone.
  The record gets a `failure_detail` saying what is missing. Nothing is deleted and nothing is moved
  back by the sweep.
- **Registration is the only way back.** `register_package` already verifies the manifest and every
  declared file's size and hash; it now also reinstates a `MISSING` record it finds (state
  `INSTALLED`, `verified_at` set, `failure_detail` cleared) and its artifact (`AVAILABLE`). Only
  `MISSING` is ever reinstated: a record in another state is left as it is. A file that came back
  changed fails verification, so the record stays `MISSING`.
- **The real profile calls the sweep** in `prepare`, before it registers what is installed, so on
  every start the catalog says what is on disk and a package that left the machine is `MISSING`. The
  planner already offers only `INSTALLED` exports, so a missing package is refused (the runtime is
  unavailable), never substituted by another one. A package moved to another machine records a new
  installation and the old one stays `MISSING` (a library opened elsewhere reports the dependency,
  as the owner decided in issue #80).

- **The library's own dependencies are reported** (found by the independent review; issue #80 asks for
  it): `missing_dependencies(session)` names, as "key version", every package whose models produced
  `ACTIVE` vectors the library still holds and that has no `INSTALLED` export on this machine. A
  different package installed here never stands in for it (vectors of another space are never
  compared); a space with no known package is named by its key. The real profile reports it as the
  `library_packages` capability (so the app opens `DEGRADED`) and `/readiness` gains an optional
  `missing_dependencies` list, present only when something is missing.
- **Two sweep corrections from the same review:** an artifact already known not to be `AVAILABLE`
  (the startup check found it gone) is swept without looking at the disk, so a denied `stat` cannot
  leave a record `INSTALLED` that registration then cannot reinstate; and `NotADirectoryError` (a
  folder above the file became a file) counts as absence like `FileNotFoundError`.

## Tests

`tests/integration/test_runtime_sweep.py` (20): nothing changes while the files are present; one
missing model file marks only its record and the planner refuses; a missing package marks everything
under it; the sweep repeats harmlessly; registering the restored package reinstates every record and
artifact and the planner offers it again; a swapped file is refused and stays `MISSING`; an artifact
the startup check marked missing is swept and reinstated; an unexaminable file is not treated as gone;
the same package at another place leaves the old record `MISSING`; only `MISSING` is reinstated.
`test_real_profile.py` checks `prepare` runs the sweep. Mutation-tested: ignoring the artifact state,
treating an unexaminable file as gone, reinstating any state, not reinstating either record kind, not
resetting the artifact, and `prepare` skipping the sweep each fail a test (three survivors on the first
pass were closed by new tests).

## Verification

- Full gate: see the PR (ruff, `mypy` on both platforms, `pytest --cov`).

## Open issues / follow-ups

- The shell does not yet show `missing_dependencies` to the user; a screen for "restore this
  package" belongs with the installer (M8).
