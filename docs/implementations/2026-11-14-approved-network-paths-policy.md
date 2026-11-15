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
    each link's target is read from the link itself.
  A link that leads to an unapproved share is refused unseen; a UNC path with `..` is refused rather
  than collapsed. With `approved=None` (the default) every network target is refused as before.
- **One walk, by retained no-follow handles, for the check and for the open.** `local_target` and
  `open_local` share `_resolve`/`_walk` (`NtCreateFile`): the volume by the NT device name the drive
  letter was checked against, or `\??\UNC\server\share` for an approved share; then each component
  relative to the handle before it, every one with `FILE_OPEN_REPARSE_POINT`, so no link or junction
  is ever followed. A symbolic link or junction met on the way is *read* from its open handle
  (`FSCTL_GET_REPARSE_POINT`, `parse_reparse`) and its target resolved again from the text; any other
  reparse point (a cloud file already on disk excepted) is refused; on a share every link is refused.
  The first version looked at each component by absolute path (`FindFirstFileW`, `os.readlink`), which
  a directory swapped for a link to an unapproved share between two lookups could turn into a contact
  (found in review, below): those calls are gone. `open_local` keeps the last handle, which must be a
  disk file (`GetFileType`; a folder raises `IsADirectoryError`, a missing file `FileNotFoundError`, a
  share that cannot be reached the Windows `OSError`), hands it to Python and asks Windows where it
  really is: for a local file the NT name must equal the resolved target; for a share the final UNC
  name must still be inside an approved root. Nothing is read before all of that holds.
  `local_target` for an approved UNC path is decided on text and opens nothing.
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

## Review (Codex, read-only, in a disposable worktree) and answers

1. *Critical: the check walked by absolute path, so a directory swapped for a link to an unapproved
   share between two lookups was followed, and contacted, before `approved()` ran.* Fixed by the one
   walk above: the check itself now opens each step relative to a held handle without following, so
   a swapped-in link is read and judged, never opened. Regression tests
   (`test_network_open.py`, `swap_when_opening`): a directory becomes a link to an unapproved share
   between steps, with zero contacts recorded; to a local folder (judged by where it now leads); to
   an approved share (read from it); a directory renamed after it was opened is caught by the final
   name; a drive letter remapped after the check is refused. The old `FindFirstFileW` entry reader and
   its tests were replaced (the tests of the refusals they proved now fake the opened step's
   attributes instead of the lookup).
2. *Required: `\\server\pipe\name` was approvable.* `PIPE` and `MAILSLOT` are refused as share names
   (with `DavWWWRoot` and `$` shares), in the approvals and the path check alike; tests for both.

## Decisions

- **The race is closed by retained handles with no-follow, not by a recheck.** The first version
  followed a link planted after the walk inside the open itself, which could reach an unapproved
  share before the final-path check could object. Now every step is `FILE_OPEN_REPARSE_POINT` and a
  reparse point is refused, so a swap cannot redirect anything, and opening the volume by the device
  the letter was checked against also closes a drive letter being remapped after the check. Parent
  handles are opened with full sharing so the walk disturbs nobody; each relative open is atomic, so
  holding the parents is not what makes it safe.
- **A share is opened by the same walk, but no link on it is followed or read:** a server-side link
  is a reparse point and is refused, and the final-name check requires the file to still be inside
  an approved root. Windows does not follow a remote-to-remote symlink by default; if a machine
  enables it, the final-name check still refuses a result outside the approved roots (after the
  contact the link caused: stated, not hidden).
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
