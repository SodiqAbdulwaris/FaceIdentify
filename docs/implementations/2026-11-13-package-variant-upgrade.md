# A registered package that only adds variants is upgraded in place

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** follow-up to the DirectML work (owner requirement 2026-11-12: use the
  GPU when there is one); persistence 18
- **Status:** done, and applied to the development laptop's two state roots (below)
- **Commits:** PR (number recorded when merged): `feat(runtime): upgrade a registered package that
  only adds variants`

> **Delegated decision 2026-11-13** (orchestrating session, under the owner's delegation of
> 2026-11-09; the owner may reverse it): the in-place upgrade, the smaller of the two designs in
> [the readiness entry](2026-11-13-readiness-execution-device.md). Spec text in
> `PERSISTENCE_IMPLEMENTATION.md` section 18 and beside `POST /runtime/models/install` in
> `API and Contracts.md`.

## What changed

- `manifest.only_adds_variants(registered, offered)`: true when every field but `variants` is
  identical (key, version, requirements, components and their contracts, exports and their weights'
  digests and sizes) and every registered variant is still there, unchanged.
- **Registration** (`registration.py`): a different manifest under a registered key is accepted when
  it only adds variants. The package row takes the new manifest, the new variants and their
  compatibility rows to the existing representation space are added (the find-or-create code that
  was there), and the installation's manifest artifact takes the new file's digest and size, all in
  the registration's savepoint. Anything else is refused as before.
- **The package store** (`package_store.py`): a complete installed package is replaced by one that
  only adds variants. The new one is staged and verified while copying as for any install; the old
  directory is moved into staging, the new one published, the old one removed. If publishing fails,
  the old one is moved back; a crash between the two moves leaves both complete in staging and
  recovery publishes one, either of which is consistent with the library (registration follows what
  is published when the library next opens).

## Why no stored vector or decision changes

A representation space is identified by the weights' digest and the contracts, not by the provider,
variant or device (owner decision 2026-10-02). The upgrade refuses any change to those, so the
DirectML variants attach to the space the stored vectors are already in. On 2026-10-15 the DirectML
and CPU embeddings of the same faces agreed to 2.4e-7, and on 2026-10-16 the operating point gave
identical decisions on DirectML.

## The owner's case

The live package (installed before 2026-10-15) and the package both installers write today
(`scripts/install_reference_models.py` and M8's `install_models`) differ only by the two DirectML
variants: every other field is identical and the four existing variants are kept, so
`only_adds_variants` holds for both (checked against the live manifest, read only).

## Verification

- `tests/unit/test_runtime_manifest.py`: the rule holds for added variants and for an identical
  manifest, and fails for changed weights, a changed contract, a changed or removed variant, another
  version, or variants that are not a list.
- `tests/integration/test_runtime_registration.py`: the upgrade keeps the package, installation,
  export and representation space, adds the DirectML variants linked to that same space and updates
  the manifest artifact's digest; other weights, another contract or a removed variant are still
  refused; a failure part way leaves the registered package as it was, even if the caller commits.
- `tests/integration/test_runtime_package_store.py`: the store upgrade replaces the package and
  leaves nothing staged; other weights with more variants are still refused; a crash after the old
  package was moved aside, or after the new one was published, recovers to one complete package; a
  publish that fails keeps the old package published.
- Those three files: 220 passed; ruff and mypy clean.

## Applied on the development laptop (2026-11-13)

**Decision** (delegated, 2026-11-13, within the owner's permission of 2026-11-12 to install the
DirectML version if it helps): upgrade the package at store level in the two state roots, after the
upgrade path merged. The desktop app's library (`%APPDATA%\io.github.sodiqabdulwaris.faceidentify\library`,
the shell's default since no saved choice or environment variable is set) turned out to be a
**development-profile** library (`library_profile = DEVELOPMENT`: 13 faces as 64-dimensional
development vectors, no real package ever registered), which the real profile refuses to open by
design; it was left untouched, and no library was upgraded or migrated.

| State root | Backup (dated, restore steps beside it) | Package before, after | Store check | A scratch real library on it |
|---|---|---|---|---|
| `%LOCALAPPDATA%\io.github.sodiqabdulwaris.faceidentify\state` (the desktop app's) | `local-models/backups/20261113T111732Z-app-state-runtime-packages` | 4 files, 191,310,429 bytes; 4 files, 191,310,827 bytes (the manifest gained the two DirectML variants) | verifies; CPU, CUDA and DirectML variants | `runtime_package: READY`, `execution_provider: DmlExecutionProvider`, `provider_fallback: NONE`, `execution_device: NVIDIA GeForce RTX 4070 Laptop GPU` |
| `local-models/state` (developer and gate tooling) | `local-models/backups/20261113T111817Z-dev-state-runtime-packages` | the same | the same | the same |

Untouched: both policy files (digests compared before and after), all three index folders (the app's
two and the stale 3-vector `f0fd4e92c8c8492097e2307e82000af9`), the development-profile library, and
the six evaluation-gate libraries (each has its own `local-state` folder, so the developer state root
upgrade cannot reach them). `local-models` went from 594 to 599 files: the second backup's four files
and its restore note. The scratch libraries used for the checks were deleted. To restore either state
root: stop the app, replace its `runtime/packages` folder with the backup (the `.RESTORE.txt` beside
each backup says exactly how).

