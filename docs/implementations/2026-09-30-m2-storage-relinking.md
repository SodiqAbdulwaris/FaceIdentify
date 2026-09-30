# M2: Storage Manager, relinking

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (relinking; workspaces, recycle/restore, usage and cleanup follow)
- **Commits:** PR (number added when opened): `feat(sources): relink a missing referenced original`,
  `test(sources): add relinking tests`, `docs: record relinking`

## What changed

- `backend/app/sources/referenced_artifacts.py`: `relink_referenced_artifact(session_factory, roots,
  artifact_id, candidate, *, clock)` and `RelinkMismatchError`. It reads the artifact, inspects the
  candidate outside any transaction (`inspect_referenced_file`, so the same refusals as an import),
  requires the candidate's size and SHA-256 to equal the recorded fingerprint, then makes a
  state-guarded write: `MISSING` → `AVAILABLE`, `external_path` = the candidate's resolved path,
  failure code and detail cleared.
- Tests: 13 more in `tests/integration/test_referenced_artifacts.py` (now 47).

## Why

TST-025 lists relinking. API and Contracts §59: "Relinking a referenced Source must verify that the
selected candidate represents the expected underlying media. Selecting genuinely different media is
replacement, not relinking. V1 does not automatically scan entire disks."
IMPLEMENTATION_ARCHITECTURE §23.5: "offer Locate File; verify a relink appropriately."

## Decisions

- **"Represents the expected media" means the same bytes**: equal size and SHA-256 to what was
  recorded at import. It is the only check that cannot be fooled by a renamed or re-encoded file. A
  candidate that differs is a `RelinkMismatchError` and nothing changes. Replacing an original with
  different media is a separate operation that does not exist yet.
- **Only a `MISSING` artifact is relinked.** "Locate File" is offered for a missing original; an
  `AVAILABLE` one needs no relink, and running `reverify_referenced_artifact` first settles a file the
  user moved before the application noticed.
- **An artifact with no recorded fingerprint cannot be relinked**: there is nothing to verify
  against. It cannot arise through this code, which always records one (see the previous entry).
- **`original_filename` is kept** as import-time provenance; only the location changes.
- **No automatic search.** The candidate always comes from the user (API §59).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 416 passed (13 new, 0 regressions in the 403
  before); `backend/` coverage 100%. The test file was run 3 times in a row: 47 passed each time.
- Mutation checks (each reverted, byte-identical by `diff`): 9. Eight caught: skipping the
  fingerprint comparison, comparing size only, the MISSING-only state guard, the no-fingerprint
  refusal, the write's from-state widened (caught by the race test), skipping the inspection, and
  recording the unresolved path, which **survived** at first and is now caught by a test that
  relinks through a junction. Comparing only the SHA-256 is an *equivalent* mutant: equal hashes
  mean equal content, so the size comparison is redundant with it and kept as a cheap explicit check.

## Open issues / follow-ups

- Temporary workspaces, recycle/restore, storage usage and conservative cleanup remain for TST-025.
- The "Locate File" API route and its UI belong to later milestones; this is the use-case-level
  primitive they will call.
