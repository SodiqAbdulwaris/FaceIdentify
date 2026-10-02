# M3: the runtime package manifest (step 4a)

Date: 2026-10-02. Specs: Architecture sections 12 and 25.14, Persistence section 18, API and Contracts sections 78 to 80.

## What was built (`backend/app/runtime/manifest.py`)
- `parse_manifest(text)`: strict, versioned (schema 1) parsing into frozen dataclasses (`PackageManifest`, `ComponentSpec`, `ExportSpec` with `Provenance`, `VariantSpec`). Exact keys and types, duplicate JSON keys and NaN refused, every cross-reference resolves, names unique (export files case-insensitively), sha256 as 64 lowercase hex.
- `safe_relative_path`: forward-slash relative paths that cannot leave the package or be rewritten by Windows.
- `incompatibilities(manifest, facts)`: why a package is not for this machine. An unknown fact is a mismatch, never assumed fine.
- `file_problems(root, manifest)`: every declared file is present, inside the package (a link out of it is refused), of the declared size and hash; undeclared files are ignored.

## Decisions
The schema is the agent's design (the specs say only "declarative and versioned"); it mirrors the catalog tables and is recorded as a dated note in Architecture 12.2 for the owner to confirm (issue 71). Provenance (`license`, `source`, `redistributable`) is mandatory so unclear weights are recorded, not omitted (issue 69).

## Not in this step
Staging, copying into managed artifacts, catalog registration, activation, rollback, removal and interrupted-install recovery are step 4b. Content-addressed deduplication of blobs across packages is not built.

## Verification
82 unit tests (every malformed case with its message; a directory junction escaping the package). 30 mutations of the guards, all caught; one redundant guard (a leading `/`, already an empty segment) was deleted.
