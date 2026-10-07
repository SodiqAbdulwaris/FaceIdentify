# M4 W3.5: identities and occurrences, read-only

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045 (endpoint schemas)
- **Status:** partial; W3 continues with system status; observation reads, media for face crops and the correction commands (M5) are not built
- **Commits:** PR (this change): `feat(api): read identities and occurrences`

## What changed

- `backend/api/routes/memory.py` (new), all behind the `Library` dependency:
  - `GET /identities` and `GET /identities/{id}`: an identity with its representative observation
    (id, source, normalized bounding box, `face_crop`), `occurrence_count`, `source_count`
    (distinct sources) and timestamps; newest first, keyset-paginated.
  - `GET /sources/{id}/occurrences` and `GET /identities/{id}/occurrences`: each occurrence with its
    source name, identity, kind, representative observation and `created_at`; newest first,
    keyset-paginated, the cursor bound to its scope (the source or identity id).
  - **Only authoritative data is shown.** `PENDING` observations, occurrences and identities (a
    run's private output) are never listed or returned; an identity that is not `ACTIVE` is 404
    `IDENTITY_NOT_FOUND`; a representative observation that is not `ACTIVE` is absent; counts
    include only `ACTIVE` occurrences. Merged, split and forgotten identities are not exposed
    until the M5 correction commands define how they are shown.
  - `face_crop` is always `null`: no face crops are generated yet (`observations.face_crop_artifact_id`
    is never written); the field is in the contract so it does not change when they are.
- `backend/api/pagination.py`: `created_cursor`, `created_key` and `older_than` hold the
  `(created_at, id)` newest-first keyset once; the jobs and runs routes now use them instead of
  their own copies.
- `tests/fixtures/api.py`: `Api.perception`, so a test can change what the planted perception sees.

## Why

W3 of the completion plan: after processing, a person must see which faces were found in an image
and which identity each belongs to, and open an identity to see where else it appears.

## Decisions

None new. Open for the recycle command (no recycle route exists yet): whether the occurrences of a
recycled source still appear under an identity and in its counts. These reads do not filter on the
source's state, so today every `ACTIVE` occurrence is shown; the product decision belongs with the
command that creates recycled sources, not here. Observation list/detail (`/observations`) and `/occurrences/{id}` are left out: the UI's
M4 views are served by occurrences (each carries its representative observation) and identities.

## Verification

- `tests/integration/test_api_memory.py` (6, real library, planted perception): a processed image
  shows its face (a non-square box, so width and height cannot be swapped) and the identity made
  for it; the same face in two images is one identity with two occurrences and pages correctly;
  counts distinguish occurrences from sources (two appearances in one source); cursors are bound
  to their source and identity; identities and occurrences page newest first through ties without
  loss or repeats; private (`PENDING`) observations, occurrences and identities are never shown;
  unknown sources and identities are 404. `memory.py` is at 100% line and branch.
- Mutation probes (17 on memory and pagination, plus 3 added for scope binding): all killed after
  tests closed the survivors (distinct-source count, cursor scope binding, box orientation). One
  survivor is equivalent and was not tested: the identity list's cursor context replaced by another
  constant that is still unique to that endpoint.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,501 passed**, 100% coverage.
