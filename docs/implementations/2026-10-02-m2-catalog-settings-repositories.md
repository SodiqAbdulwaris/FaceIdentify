# M2: RuntimeCatalog and Settings repositories

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M2 · TST-022; GitHub issue #32 (the last item)
- **Status:** done; with this, every repository of persistence §26 exists
- **Commits:** PR #61: `feat(runtime): runtime catalog and settings repositories`

## What changed

- `backend/app/settings/repository.py`: `SettingsRepository` over the three singleton groups (`SettingsGroup`):
  `bootstrap` (one `INSERT ... ON CONFLICT DO NOTHING` per group, so a repeat or a race creates each row once and returns
  what it created), `get` (fresh), and `update` (the shared optimistic-locked `UPDATE`: applies at the revision the caller
  read, bumps it, stamps `updated_at`). The groups have no value columns yet; a name that is not a setting of the group
  (including `id`, `revision`, `updated_at`) is a `ValueError`, so a typo is never silently dropped and the first typed
  settings need no change here.
- `backend/app/runtime/repository.py`: `RuntimeCatalogRepository`: `add` (any catalog row, flushed so its constraints are
  checked now), reads (`component_by_key`, `versions_of` and `exports_of` oldest first, `variants_for_space` through the
  validated mapping in a stable order, `calibration_profiles` newest first, `package_by_key`, the installation lists) and
  the only changes to existing rows: `transition_export_installation` / `transition_package_installation`, guarded by the
  state the caller expects. Versions, exports and calibration profiles are immutable (§18), so there is no update for them.
- `tests/integration/test_catalog_settings_repositories.py` (18).

## Why

PERSISTENCE_IMPLEMENTATION §26 ("cohesive catalog reads/writes; singleton group reads/updates") with §18 and §19.

## Decisions

- Settings: no value columns are invented. The `update` signature is ready for the first typed setting.
- Catalog: the value sets of `state`, `kind`, `format`, `provider` are still open (CONTEXT question 11), so every state is
  the caller's string; a transition only needs the expected state.
- The package-membership association tables are not built (§18: "only when the trusted manifest needs relational querying").
- Installation transitions write the times and failure detail as given (`None` clears them), so a success clears an earlier
  failure's detail.

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1052 passed, backend coverage 100%.
  Every guard was broken, shown to fail a test and restored byte-identical (17 mutations; one survivor, the versions'
  `ORDER BY`, exposed that the unique index's natural order hid it, and the test now runs the dates against the version
  strings). The racy tests ran 3 times.
- **Not verified:** the repositories under real use cases (not wired in yet).

## Open issues / follow-ups

- Typed settings (and their `update` tests) arrive with the features that own them.
