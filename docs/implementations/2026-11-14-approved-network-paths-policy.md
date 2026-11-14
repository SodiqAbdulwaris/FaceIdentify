# Approved network paths in the face-search path check, and the retained-handle open (issue #174, PR B)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** issue #174 (second part, step B of [the plan](../plans/NETWORK_ROOTS_PLAN.md)); TST-056
- **Status:** partial: an approved share can be read and the walk-to-open race is closed; the read is not yet bounded or abandonable (PR C), and there is no screen (PR D)
- **Commits:** PR (number recorded when merged): `feat(search): read approved network shares, open by handle walk`

## What changed

- `backend/infrastructure/storage/unc.py` (new): the pure text rules for a UNC path (`unc_parts`,
  `is_device_component`, ASCII-folded `key_of`/`is_inside`), moved out of `network_roots.py` and
  `local_path.py` so the approvals and the path check can never disagree about what a UNC path is.
- `local_path.local_target(path, approved=None)`: a UNC path, however reached, is decided on its
  canonical text by the `approved` callback, before any outbound access. New ways to reach one:
  - a **mapped drive**: the DOS device (`QueryDosDeviceW`, object manager only) of the shape
    `\Device\[Mup\;]LanmanRedirector\;Z:<id>\server\share[\folder]` is the share it names; a
    **subst** of `\??\UNC\server\share` likewise. Anything else that is not a local volume (a bare
    `\Device\Mup`, DFS, WebDAV, RDP drives, no answer) stays refused;
  - a **symlink** whose target is a UNC path, at any depth (nested with junctions and other links);
    the existing loop reads each link's target from the link itself.
  A link that leads to an unapproved share is refused unseen; a UNC path with `..` is refused rather
  than collapsed. With `approved=None` (the default) every network target is refused as before.
- `local_path.open_local(path, approved=None)` now opens by a **walk of retained handles**
  (`NtCreateFile`): the volume by the NT device name the drive letter was checked against, or
  `\??\UNC\server\share` for an approved share; then each component relative to the handle before
  it, every one with `FILE_OPEN_REPARSE_POINT` (no link or junction is followed) and refused if the
  opened entry is a reparse point (a cloud file already on disk excepted); the last as a
  non-directory. The handle must be a disk file (`GetFileType`) and is then handed to Python. A
  folder raises `IsADirectoryError`; a file that is missing raises `FileNotFoundError`; a share that
  cannot be reached raises the Windows `OSError`. Finally Windows is asked where the handle really
  is: for a local file the NT name must equal the resolved target (as before); for a share the
  final UNC name must still be inside an approved root. Nothing is read before all of that holds.
- `backend/api/routes/face_search.py`: the path form passes `NetworkRoots(...).approves`; the
  `400 QUERY_PATH_NOT_LOCAL` message now says the path is not on this computer or an approved
  location and how to proceed (code unchanged, path never echoed).
- Tests: `tests/unit/test_network_open.py` (38), `tests/integration/test_api_face_search_network.py`
  (5), `tests/fixtures/fake_share.py`. In `tests/unit/test_local_path.py` two tests were adapted to
  the new open (the spy on `Path.open` became a spy on `_as_file`; the `local_target` stand-in takes
  the new argument): the assertions are the same, and the other 105 are untouched.

## Why

The owner's locked decision (2026-10-14) acceptance tests: an approved UNC share and mapped drive
work for the same image; an unapproved host or share is denied before any outbound access; nested
reparse points and link swaps are decided by the resolved target; device namespaces, pipes,
directories and bypasses by separators, casing or normalisation are refused; the identity of what is
opened is validated, not the submitted string; and the documented race is closed.

## Decisions

- **The race is closed by retained handles with no-follow, not by a recheck.** The first version
  followed a link planted after the walk inside the open itself, which could reach an unapproved
  share before the final-path check could object. Now every step is `FILE_OPEN_REPARSE_POINT` and a
  reparse point is refused, so a swap cannot redirect anything, and opening the volume by the device
  the letter was checked against also closes a drive letter being remapped after the check. Parent
  handles are opened with full sharing so the walk disturbs nobody; each relative open is atomic, so
  holding the parents is not what makes it safe.
- **Remote components are not pre-walked.** Reading a share's directory entries to look for links
  would contact the host before the open does and add nothing: the no-follow open refuses a server
  side link, and the final-name check requires the file to still be inside an approved root. Windows
  does not follow a remote-to-remote symlink by default; if the owner's machine enables it, the
  final-name check still refuses a result outside the approved roots (after the contact the link
  caused: stated, not hidden).
- **The effective path is decided on canonical text** (`unc_parts` rebuilt), and the open uses that
  text, never the submitted string (review point 5 of PR A).
- A **mapped drive** is trusted only in the SMB redirector shape above; anything else is refused.
- `QUERY_PATH_NOT_LOCAL` keeps its code (existing contract and tests); only its message changed.
- Until PR C lands, a hung approved share can hold a search thread and one of the three search
  slots. Approval is a deliberate act and the API only exists to be used with PR D, but this is the
  stated window; PR C closes it.

## Verification

- `uv run pytest -q tests/unit/test_local_path.py tests/unit/test_network_open.py
  tests/unit/test_network_roots.py tests/integration/test_api_face_search.py
  tests/integration/test_api_face_search_network.py`: pass; `local_path.py`, `unc.py` and
  `network_roots.py` at 100% line and branch coverage; ruff, mypy and `mypy --platform linux` clean.
  Full gate: see the PR.
- **Not exercised: a real share.** Creating an SMB share needs administrator rights
  (`net share` answered `System error 5: Access is denied` for the user running this work), and
  that was not worked around. The share is faked at the Win32 boundary (`tests/fixtures/fake_share.py`:
  the absolute `\??\UNC\...` open is recorded and redirected to a folder; everything after the
  first step is real). What is therefore unproven is SMB's own behaviour: that `NtCreateFile` with
  `FILE_OPEN_REPARSE_POINT` against a real server reports the reparse attributes
  `GetFileInformationByHandleEx(FileAttributeTagInfo)` expects, and that `GetFinalPathNameByHandleW`
  in DOS form returns `\\?\UNC\server\share\...`. Both are documented Windows behaviour. The scratch
  folder used for the probe was deleted.

## Open issues / follow-ups

- PR C: bounded, abandonable network I/O (this PR's `open_local` can block on a hung share).
- PR D: the settings screen. #174 stays open; this entry does not close it.
- Referenced import from a share (`inspect_referenced_file`) is a different trust question (#179).
