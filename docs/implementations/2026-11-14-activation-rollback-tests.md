# A failed activation of the models keeps the application working (TST-082)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** M8 step 4 and 7(c); TST-082 (and the app-level half of TST-080)
- **Status:** tests added and passing; no product code changed. M8 is not declared done by this
- **Commits:** PR (number recorded when merged): `test(runtime): a failed activation keeps the app working`

## What changed

`tests/integration/test_real_profile.py`, six tests through the real profile over HTTP (the real
package store, the real install route, `prepare`, readiness, the scheduler and the executor; a
fixture package and a stand-in perception client, as in the rest of that file):

- **Control:** an upgrade of the installed package (the same package with a DirectML variant per
  export) answers 201, the published package has the four variants, the library's catalog has the
  DirectML variants registered (so the route did run `prepare` again), readiness is `READY` and
  the next picture is processed.
- **A damaged upgrade** (one file has other bytes than its manifest says): `400
  MODEL_SOURCE_INVALID`.
- **An upgrade that cannot move into place** (the rename of the new package fails after the old one
  was moved aside): `400 MODEL_SOURCE_INVALID`.
  After each of these two: the previous manifest is byte-identical, `verify` finds every file
  intact, nothing is left in the installation folder, readiness is `READY` with `runtime_package`
  `READY`, the catalog still has only the CPU variants, and the next picture is processed to
  `COMPLETED`.
- **The limit of the rollback: the new package cannot move into place and the old one cannot be
  moved back either** (both renames fail, as when both are locked). The request is still `400
  MODEL_SOURCE_INVALID`; nothing is published under the key, so readiness says `DEGRADED` with
  `runtime_package` `UNAVAILABLE` (it does not pretend); the old package is whole in the
  installation folder; the next start publishes it again, reports `READY` and processes a picture.
  So in this one case the previous configuration comes back at the next start, not at once.
- **An upgrade killed half way** (at the step after the old package is moved aside, and at the step
  after the new one is published): the application then starts, recovers one complete package (the
  old or the new), reports `READY`, and processes a picture.

## Why

The M8 plan's evidence table listed "activation rollback after a failed self-check (TST-082)" as not
verified. The store's own tests (`tests/integration/test_runtime_package_store.py`) already cover
the refusals and the crash points; what was missing was the application: does it still serve and
process after an activation fails? The owner asked for this on 2026-11-14.

## Decisions

None new. Two things the plan words differently from what was built, recorded here so the tests
are read against the code and not the plan:

- The plan (step 4) describes a previous runtime folder kept until the new one passes a self-check,
  selected "by a pointer written last". What was built (2026-11-13, delegated) has no pointer: a
  package is published under its key by one rename, a complete package is replaced only by the same
  package with more variants, and during that replacement the old one is moved aside and moved back
  if the new one cannot be published (`RuntimePackageStore._swap`).
- The self-check is the readiness report (delegated decision in the step 5(b) entry), not a
  separate run. So "a failed self-check" is tested as: the install is refused or fails, and
  readiness and a real processing run afterwards show the previous configuration working.

## Verification

- The six tests pass, three runs in a row
  (`uv run pytest tests/integration/test_real_profile.py -k "activat or upgrade or put_back"`);
  with `test_runtime_package_store.py` and `test_api_runtime_models.py`: 130 passed.
- Independent review (Codex CLI, read-only, posted on the PR): three findings, all addressed (the
  control now proves re-registration; the both-moves-fail case was added; the plan's step 4 now
  carries a note of what was built).
- The rollback test fails when the rollback is removed: with the move-back in `_swap` replaced by
  `pass`, the "cannot move into place" case fails (the published package is gone); restored after.
- `uv run ruff format --check`, `uv run ruff check`, `uv run mypy`: clean. Full gate: CI on the PR.

## Open issues / follow-ups

- When both moves fail, the models are unavailable until the next start (tested above). The
  application could publish the set-aside package again without a restart; not built, because the
  case needs both folders locked at once and a restart recovers it.
- Not covered: a package that is published but then fails registration (`prepare` reports
  `runtime_package` `UNAVAILABLE` and the library stays open, by the existing
  `test_the_selected_package_being_damaged_makes_it_unavailable_not_the_library_failed`). The store
  admits only the same package with more variants as a replacement, so no input is known that
  publishes and then fails to register; none was constructed.
- The same check on the installed build (the frozen backend) is not part of `check_installed.py`.
