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
95 unit tests (every malformed case with its message; a directory junction escaping the package). 38 mutations of the guards, all caught; two redundant guards were deleted (a leading `/`, already an empty segment; a control-character test on paths, already done by the string reader).

## Review
OpenCode (`opencode/big-pickle`, plan agent, disposable worktree, under a watchdog: the first attempt hung for 15 minutes with no output and was killed; see the process note below). No blocker. Fixed: a bad byte or deep nesting escaped as `UnicodeDecodeError` or `RecursionError` instead of `ManifestError`; `schema_version: 1.0` was accepted; control and invisible characters were accepted in names and values; a variant matched its export case-sensitively while duplicates were detected case-insensitively; fact names were compared case-sensitively and a non-text fact value crashed; `file_problems` could raise on a link loop, and its docstring now says that an empty result does not bind the check to a later copy (step 4b must verify what it copies); an unused parameter was removed. Left as noted: reserved-name edge cases that Windows does not treat as devices (checked against the real filesystem), and NFC/NFD collisions (the app is Windows-only).

Process note: OpenCode runs only without a custom config (a config makes its free tier refuse); a watchdog (`scratchpad/watchdog.ps1`, sampling CPU, output and connections every 30 s, killing on 4 minutes without change) now wraps review runs.
