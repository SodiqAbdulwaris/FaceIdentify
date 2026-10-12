# Runtime 04 Packages and the catalog

## 1. What this is and why it exists

Model files are large, licensed, machine-specific and never committed. The application treats them as **runtime packages**:
a folder of weight files plus a **manifest** that says exactly what is inside (names, sizes, SHA-256 hashes, which machine it is
for). Two separate steps follow: **installing** puts a verified package on this machine, and **registering** records in the
library's database *which components, versions and exports* it contains, so every observation and vector can name the model that
made it. A vector's *space* is a recorded identity, not an assumption.

## 2. Where it lives

| Thing | Where |
|---|---|
| The manifest (strict parse, safe paths, machine compatibility) | `backend/app/runtime/manifest.py` |
| Atomic install: stage, verify, publish, recover | `RuntimePackageStore` in `backend/app/runtime/package_store.py` |
| Registration into the catalog (components, versions, exports, variants, spaces) | `backend/app/runtime/registration.py` |
| Building the reference package from two ONNX files | `backend/app/runtime/reference_package.py`; script `scripts/install_reference_models.py` |
| Catalog tables | `backend/app/runtime/models.py`, `repository.py` |
| Tests | `tests/unit/test_runtime_manifest.py`, `test_reference_package.py`, `tests/integration/test_runtime_package_store.py`, `test_runtime_registration.py`, `test_runtime_sweep.py` |
| Spec | `IMPLEMENTATION_ARCHITECTURE.md` section 12; `PERSISTENCE_IMPLEMENTATION.md` section 18 |

## 3. How it works

- **Manifest** = data, never logic. Parsing is strict: exact keys and types, no duplicate keys, no unsafe file paths (nothing that
  leaves the package or that Windows could rewrite). It lists components, model exports (`file`, `format`, `precision`, `sha256`,
  `size_bytes`, `input_contract`, and **provenance**: license, source, whether redistributable), the runtime variants (an export
  with a provider and device kind) and the machine facts (`os`, `architecture`) it is for. A package for another machine is refused.
- **Atomic install** (`<local state>/runtime/packages/<key>`): copy each declared file into a staging folder
  (`<local state>/installation/<key>.<token>`) *hashing the bytes actually copied*; copy the manifest; write the `.installed` marker
  last (holding the manifest's hash); publish with one `os.rename` of the folder. A package is therefore absent or complete,
  and a crash leaves staging debris that `recover` finishes or removes. Installing the same package again changes nothing; a
  different package under an installed key is refused and the original kept. After a power cut a file entry could in principle
  be missing: `verify` finds it, and reinstalling is cheap.
- **Registration** runs in the caller's transaction on startup (the real profile's `prepare`): find-or-create `Component`,
  `ComponentVersion`, `ModelExport`, `RuntimeVariant` rows; **catalog rows are immutable** (a row that exists with different
  content is an error, never an update); each export's file and the manifest become `REFERENCED` artifacts (the bytes stay
  machine-local); for every export of a face-representation component one **representation space** is created.
- **What a space is.** Its identity (the `semantic_key` fingerprint) is the weights digest, the dimensionality, the preprocessing
  contract version, the normalisation and its contract version and the model compatibility version, **not** the execution
  provider, the device or the model's human-readable `family` label. So a CPU package and a CUDA package of the same weights
  share a space; two precisions of one model are two spaces.
- **A library moved to another machine** finds its installation records `MISSING` and says so; it never substitutes another package.
- **Sweep**: startup marks records whose files left this machine `MISSING` ([recovery](../architecture/06-recovery.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12 (Linux).**

```bash
uv run pytest tests/unit/test_runtime_manifest.py tests/unit/test_reference_package.py tests/integration/test_runtime_registration.py -q
```

Observed: `109 passed` for the two unit files and `56 passed` for registration. The install tests:
`uv run pytest tests/integration/test_runtime_package_store.py -q` gave `3 failed, 38 passed` on Linux: the three failures are the
race tests (`test_two_installers_racing_for_one_key_leave_one_complete_package` and two siblings), which rely on Windows refusing to
rename a folder over another; they are meant for Windows. The 38 that passed include
`test_a_package_is_installed_complete_and_nothing_is_left_staged`, `test_installing_the_same_package_again_changes_nothing`,
`test_a_package_for_another_machine_is_refused_before_anything_is_written` and `test_what_is_installed_is_what_was_verified_while_copying`.

*(Needs the local weights; unverified here.)* The real install is a script, with the flags it declares:

```bash
PYTHONPATH=. uv run python scripts/install_reference_models.py --models-dir local-models/buffalo_l \
  --detector det_10g.onnx --embedder w600k_r50.onnx --local-state-root <your local state folder>
```

The weights are never committed (`local-models/` is local only). The script prints what it installed; the real profile then
registers the package at its next start and `runtime_package` becomes `READY` ([profiles](../architecture/04-profiles.md)).

## 5. Change it

A new model is a new package and, if its pre/postprocessing differs, a new worker module and contract version, not an edit to
the existing one (`perception_handlers.py` knows exactly two contracts). The manifest schema is versioned; changing it needs the
manifest tests first and a documented migration path for installed packages. Never write a hash by hand: the builder measures it.

## 6. Break it on purpose

In a *scratch* copy of a test fixture package, change one byte of a weight file and call `verify` (the sweep and store tests do):
the package is reported damaged and is not offered as a variant. That is the same check the worker applies when it hashes
the file before building a session.

## 7. Exercises

1. Why does install hash the bytes while copying?
2. Why does a CPU package and a CUDA package of the same weights share a space?
3. What is written last during install and why?
4. What happens to a library opened on another machine?

**Answers**

1. What is installed must be exactly what was verified; a file swapped between check and copy cannot slip in.
2. A space's identity is about the weights and contracts, not the execution provider.
3. The `.installed` marker with the manifest's hash: a folder with a valid marker is complete, one without is not.
4. Its installation records become `MISSING` and the app reports it; nothing else is substituted.

## 8. Related files

- Previous: [03](03-perception-client-and-providers.md) · Up: [Runtime and worker](README.md)
- [`backend/app/runtime/package_store.py`](../../../../backend/app/runtime/package_store.py), [`scripts/install_reference_models.py`](../../../../scripts/install_reference_models.py)
- [a real-model run](../../06-evaluation-and-operations/05-real-model-run.md)
