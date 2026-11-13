# M8 step 5(a): installing the face models the user obtained

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** M8 step 5(a) · TST-079, TST-080, TST-083 (R11), backend half (not `PASSING`: the screens, the recognition-mode choice and the self-check are not built)
- **Status:** done
- **Commits:** PR (number added when opened): `feat(runtime): install the user's face models against a hash table`, `feat(api): read and install the face models`, `build(api): regenerate the contract for the model routes`

## Why

M8 decision R6: the weights are never bundled and never downloaded by the application, so a fresh install has no models. The first-run flow
needs a backend that lets the user point at what they downloaded, checks it against the recorded evidence and installs it, so the owner's
requirement (a working GPU is used, otherwise the CPU, with no manual step) holds from the first run.

## What changed

- `backend/app/runtime/model_install.py`: `install_models(source, store, allow_fixture)` takes a folder (or a folder inside it) or the downloaded
  zip, copies out only the two files the application uses (`det_10g.onnx`, `w600k_r50.onnx`; from a zip by base name and never more bytes than the table says),
  checks each file's size and SHA-256 against the table of `docs/guides/INSTALLING_MODELS_WINDOWS.md`, and installs the package through the existing
  `RuntimePackageStore` (staged, verified while copying, published by one rename), with a DirectML, a CUDA and a CPU variant per model.
  A file that is not the selected model, a missing file, a non-zip, an oversized zip member or a missing path is refused and nothing is installed.
- **The test-only trust path:** under the development profile only, a folder holding `fixture.json` with `{"fixture": true}` is accepted with the
  files' own measured hashes. A production build refuses it like any file not in the table (tested).
- `backend/api/routes/runtime_models.py`: `GET /api/v1/runtime/models` (the table, the licence, whether installed) and `POST /api/v1/runtime/models/install`
  (`{path}`; `400 MODEL_SOURCE_INVALID`, `409 MODELS_ALREADY_INSTALLED`; the processing configuration is prepared again, so no restart is needed).
- `docs/specs/API and Contracts.md` section 5.8 (the spec text this step proposes), `frontend/src/api/openapi.json` and `schema.d.ts` regenerated.

## Verification

- 12 use-case tests (the table is replaced by the measured stand-in files in the tests; the real weights are never read) at 100% line and branch coverage
  of `model_install.py`, and 8 route tests. Full backend gate: see the PR description.
- Not verified: installing the real `buffalo_l` files (the weights are not available to an agent; the hashes are the ones recorded on 2026-10-16; step 8,
  the owner's machine), and a restart-free switch to the real profile: the installed package is registered by `prepare`, which the route calls, and the
  first real processing run is step 8.

## Decisions (delegated, 2026-11-13; the owner may reverse any)

- Installing the same models again answers `201` (the store is idempotent for an identical package); different ones are a `409`, because a library refuses
  a different manifest for a package it has registered (`INSTALLING_MODELS_WINDOWS.md` section 3).
- The error messages name the file, never a path, and the store's own refusals are not shown to the user.
- The path is whatever absolute path the user chose in the file dialog, including a network location, exactly as for importing an image: the user is the one reading it, the application opens no connection of its own, and every file is checked against the table before it is trusted. No rule against network paths exists in the repository (searched the specs, rules and plans); if the owner wants one, it belongs in a shared path validator for imports and models together.

## Open issues / follow-ups

- Steps 5(b) to 5(d): the recognition-mode choice, the self-check, the first-run screens and the desktop end-to-end test; the rollback tests (a corrupted package keeps the previous configuration) of TST-080 and TST-082 belong there too.
