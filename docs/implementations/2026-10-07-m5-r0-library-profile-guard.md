# M5 R0: a library belongs to one profile (issue #137)

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M5 track R, step R0; follows the M4 development profile
- **Status:** done
- **Commits:** PR to be recorded when merged

## What changed

- `backend/api/library_profile.py`: a `library_profile` key in `app_state` (`DEVELOPMENT` or `REAL`)
  is written the first time a backend opens a library and checked on every open. Opening the library
  as the other profile raises `LibraryProfileMismatchError`; there is no override. A library with no
  marker (made before this guard) is classified from what it holds: development catalog rows mean
  `DEVELOPMENT`, imported sources without them mean `REAL`, an empty one takes the requested profile.
  A refusal writes nothing, so a guess is never recorded.
- `ProcessingSettings.profile` (default `REAL`; the development profile sets `DEVELOPMENT`); the
  backend's startup claims the profile right after the library opens and before `prepare` and the
  scheduler, so a refused library never gets fake catalog rows. A refusal is the existing `FAILED`
  state with the class name `LibraryProfileMismatchError` on `/readiness`, and shutdown still releases
  the library.
- `tests/integration/test_library_profile.py`: seven tests on real SQLite and the real lifecycle.

## Why

Owner decision 2026-10-07 on the development profile's persisted catalog: enforce, not just document,
that a kept library is never opened with `--development-profile` and the reverse.

## Decisions

> **Decision 2026-10-07:** The owner chose the marker in `app_state` with no schema change.

The "development provenance on the catalog records" requirement needed no new field: the development
rows are already explicitly labelled (`contract_json {"development": true}`, export format
`DEVELOPMENT`, version `0.0.0-development`, display name "(development)", `development-*` keys). The
guard classifies a legacy library from the component keys. No cleanup or migration of development data
was built, as decided.

## Verification

- `uv run pytest tests/integration/test_library_profile.py`: 7 passed.
- Six mutations of the guard (inverted comparison, swapped classification both ways, marker not
  written, classification dropped, development keys not matched) each made the tests fail; the file was
  restored after each. Full gate results are in the PR description.

## Open issues / follow-ups

- A library first opened without `--development-profile` becomes `REAL` even if nothing was imported,
  so it can no longer be opened as a development library. This is the intended strictness; make a
  separate library for development.
- Issue #137 closes with this change.
