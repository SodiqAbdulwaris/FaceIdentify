# M3: registering an installed runtime package in the catalog (step 7, third part; issue 80, first half)

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M3 · TST-038, TST-039 (in progress); issue 80 (first half)
- **Status:** partial: registration is done. Reconciling the installation records with what is on disk (a missing package is reported, never substituted) and the backend client that writes PENDING output are the rest.
- **Commits:** PR (this branch): `feat(runtime): register installed packages in the catalog`

## What changed
`backend/app/runtime/registration.py`: `register_package(session, installed_package, *, new_id, clock)`, in the caller's transaction (it flushes, never commits). From an installed package's manifest it records:
- `Component`, `ComponentVersion`, `ModelExport` and `RuntimeVariant` rows, each **found by its identity or created**. Catalog rows are immutable (Persistence 18), so a row that exists with different content (a component's kind, a version's contract, an export's format, precision or input contract, a variant's requirements) is a `RegistrationError`, never an update. Two packages that ship the same component version and weights (a CPU package and a CUDA package) share these rows.
- A `REFERENCED`, `AVAILABLE` artifact for every export file (`MODEL_EXPORT`, with the manifest's hash and size) and for the package directory (`RUNTIME_PACKAGE`, with the hash and size of its manifest), and the `InstalledModelExport` and `RuntimePackageInstallation` rows that point at them. The bytes stay machine-local in the package directory, never in the library (Architecture 12.2).
- For **every export of a `FACE_REPRESENTATION` component, one `RepresentationSpace`**. Its identity is the owner's list (ML 18.1): model family, weights digest, dimensionality, preprocessing contract version, normalisation and its contract version, model compatibility version, and **not** the execution provider. `semantic_key` is `rs1:` + the SHA-256 of that record in canonical JSON (sorted keys, no spaces), so equal identities are one space and anything else is another; `contract_json` holds the record (plus the scheme name), `dimension`, `normalization` and `metric = COSINE` mirror it. `weights_digest` is the export file's SHA-256, so two exports of one model at two precisions are two spaces.
- For every variant of such an export, a `RuntimeVariantRepresentationSpace` row in the state `DECLARED`: the manifest claims the variant runs that export; numerical equivalence of another provider is a later validation.
- Registering the same package (same key and manifest) again returns the same ids and adds nothing; a different manifest under the same key is refused.

## Why
Issue 80 and the owner's 2026-10-02 decisions: libraries persist provenance for the components that made their data; installed packages are machine-local and only referenced; the space is a recorded identity, not an assumption (ML 18.1).

## Decisions (the agent's; for the owner to confirm)
- **What a component's manifest `contract` must say** (a convention the specs leave open; validated here, with a refusal naming what is missing): a `FACE_DETECTOR` names `preprocessing_contract`; a `FACE_REPRESENTATION` names `family`, `dimension`, `preprocessing_contract`, `normalization`, `normalization_contract_version` and `compatibility_version`. The detector's and embedder's `preprocessing_contract` are the values the worker serves (`scrfd-letterbox-v1`, `arcface-112-similarity-v1`). I did not edit Architecture 12.2 for this; if you confirm it, a dated note there is the follow-up.
- **Every export is one complete weight artifact.** The manifest has no way to say that several files are one model, so the aggregate digest scheme ML 18.1 leaves undefined is not invented; the day a model needs it, the manifest and this module change together.
- **The fingerprint scheme is pinned** by a test with a literal key: a stored `semantic_key` must mean the same thing for ever.
- **Spaces are registered `ACTIVE`** (the model's enum is `ACTIVE`/`DEPRECATED`). See open question 31 in CONTEXT: ML spec 9.2 lists other states (`REGISTERED`, `VALIDATED`, `ACTIVE`, `RETIRED`) and says V1 has only one active space for new processing. Which space a run uses is the processing configuration's choice; registration does not activate or deprecate anything.
- Installation rows start `INSTALLED`, packages `REGISTERED`, variants `REGISTERED`: state vocabularies are still open question 11.

## Verification
- `tests/integration/test_runtime_registration.py` (41 tests, real SQLite, 100% coverage of the module): everything recorded and linked; referenced artifacts with the right hash, size and path; the space identity and key; each identity component changes the key and nothing else does (a provider or an unrelated field does not); the key scheme pinned; the same weights under another provider are one space and one set of shared rows with separate installations; two precisions are two spaces; a new component version beside the old; the same weights in a new component version get their own export row but share the space; several variants differing in one respect each; registering again (also among packages that share rows, and from a fresh session) finds the same ids and adds nothing; every refusal (different manifest under a key, immutable contract, kind change, precision or input contract change, variant requirements, a tampered space record); nothing is committed on the caller's behalf and a refused registration leaves nothing once rolled back; every contract rule.
- Mutation pass: 38 mutations (each identity component, the canonical form, the scheme name, every contract and immutability guard, every lookup condition, the shared-row logic, the compatibility row, the artifact fields and the states). Survivors on the first run (the variant lookup conditions, the package artifact's hash) got tests; none survive.
- Full gate: see the PR.

## Open issues / follow-ups
- Issue 80, second half: reconcile the installation records with the package store (a package or file that is gone or changed is reported and its records marked `MISSING`; nothing is substituted), and wire it into startup recovery.
- The backend client (decode into shared memory, build the worker configuration from the catalog and the package store, call the worker, write PENDING observations and representations), including the PR 84 requirement that `model_path` be confined to the package.
- Open question 31 (space states) for the owner.
