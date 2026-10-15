# Face search by path: links, junctions and mapped drives that lead to a share are refused (issue #174)

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 backlog; issue #174 (first part); TST-056 (face search)
- **Status:** partial: the default-deny half of the owner's policy is built and tested; approved
  network roots (opt-in) and bounded network reads are not
- **Commits:** PR (number recorded when merged): `fix(search): refuse face-search paths that lead to a
  share`, `docs: record the face-search network path check`

## What changed

- `backend/infrastructure/storage/local_path.py` (new): `local_target(path)` follows a path the way
  Windows would, one component at a time, reading each symbolic link's or junction's target from the
  link itself (`lstat`, `readlink`: local volume only), and answers the fully resolved local file, or
  `None` when any step leaves the computer: a UNC or device form (`\\server`, `//server`, `\\.\`,
  `\\?\UNC\`, `\\?\GLOBALROOT`, a volume mount point `\\?\Volume{...}`), a mapped network drive
  (`GetDriveTypeW` is `DRIVE_REMOTE`; it reads the mapping and does not connect), or more than 40
  links (a loop). `\\?\C:\...` is a local drive path and is accepted.
- `backend/api/routes/face_search.py`: a JSON `{"path": ...}` query is checked with `local_target`
  before anything is read, and the **resolved** local file is what is opened. A path that leads off
  the computer is `400 QUERY_PATH_NOT_LOCAL` ("A picture on another computer or a network drive
  cannot be searched by its path…"), without echoing the path. Before, only a path that began with
  `\\` was refused (`QUERY_IMAGE_UNREADABLE`), so `Z:\` on a mapped drive, or a junction or symlink to
  a share, was read.
- Tests: `tests/unit/test_local_path.py` (19: every network and device form, local and extended drive
  paths, relative paths, a real junction to a local folder, real symlinks to a share as a file and as
  a directory at any depth and behind a junction, a relative link, a link loop, a mapped drive (the
  drive type stubbed: a mapped drive cannot be made without a share), this machine's own drive);
  `tests/integration/test_api_face_search.py`: the network forms now answer `QUERY_PATH_NOT_LOCAL`,
  and a new test refuses a symlinked file and a symlinked folder that point at a share and still
  searches through a junction to a local folder.

## Why

Issue #174 and the owner's locked decision on it (2026-10-14): network paths may be read only when
the user has approved them (per-user opt-in roots or shares), unapproved remote hosts are denied
**before any outbound access**, the effective target is validated rather than the submitted string,
device namespaces are rejected. No network root can be approved yet, so the built behaviour is the
policy's default: every network target is refused.

## Decisions

- **Default deny, not the opt-in.** The opt-in configuration (where the approved roots live, how the
  user approves one, the screen) and the bounded, cancellable network read the decision requires
  (point 6: a thread timeout does not stop an outstanding SMB read) are a larger, separate piece; until
  they exist, refusing all network targets is the only behaviour the decision allows. Not a delegated
  decision: it is the decision's own default.
- **Links are resolved by reading them, never by `Path.resolve()`:** `resolve` opens the target
  (`GetFinalPathNameByHandle`), which would contact the share while deciding.
- **The resolved local file is opened,** so a link swapped in the submitted path after the check is
  not followed; a link planted inside the resolved path between the check and the open still would be
  (marked `ponytail:` in the route; closing it needs `CreateFileW` with
  `FILE_FLAG_OPEN_REPARSE_POINT`).
- **A volume mount point is refused** rather than looked into: telling a local volume from a remote
  one through `\\?\Volume{...}` needs a volume query; refusing is the conservative reading.
- **Scope:** face search by path only, as the issue says. A referenced import from a network share is
  a different trust question (the user's own photographs on a NAS) and is listed below.

## Verification

- `uv run pytest -q tests/unit/test_local_path.py tests/integration/test_api_face_search.py`: 19 and
  23 passed. Full backend gate: see the PR.
- Not verified: a real mapped network drive (no share on this machine or in CI).

## Open issues / follow-ups

- #174 stays open for the approved network roots (configuration and screen), the bounded network read,
  and handle-level validation of the opened file.
- Referenced import (`inspect_referenced_file`) resolves with `Path.resolve(strict=True)`, which
  follows a link to a share: decide whether a referenced original may live on a network share.
