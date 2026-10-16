# Face search by path: paths that lead to a share, a device or a remote volume are refused (issue #174)

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 backlog; issue #174 (first part); TST-056 (face search)
- **Status:** partial: the default-deny half of the owner's policy is built and tested; approved
  network roots (opt-in), bounded network reads and a retained-handle walk are not
- **Commits:** PR 212 (number recorded when merged): `fix(search): refuse face-search paths that lead
  to a share`, `fix(search): close the device, reparse, subst and open-race gaps in the path check`,
  `docs: record the face-search network path check`

## What changed

- `backend/infrastructure/storage/local_path.py` (new): `local_target(path)` follows a path the way
  Windows would, one component at a time, reading each entry's own attributes and reparse tag with
  `FindFirstFileW` (not `os.lstat`: CPython reopens a reparse point it does not recognise with
  traversal, which can start a cloud download) and each link's target with `readlink`: local volume
  only. An entry that exists but cannot be examined (access denied, a bad name) refuses the path;
  names with wildcard characters are refused too, because the lookup would expand them, and answers the fully resolved local file, or `None` when any step
  leaves the computer or cannot be shown to stay on it:
  - a UNC or device form (`\\server`, `//server`, `\\.\`, `\\?\UNC\`, `\\?\GLOBALROOT`, a volume
    mount point `\\?\Volume{...}`), **also one that normalisation creates**: `\\?\C:\NUL` becomes
    `\\.\NUL` under `os.path.abspath`, so the result is checked again;
  - a Windows **reserved device name** in any component (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`,
    `LPT1-9`, the superscript variants, `CONIN$`, `CONOUT$`, with an extension, trailing dots or
    spaces) or an **alternate data stream** (any `:`);
  - a drive letter whose DOS device (`QueryDosDeviceW`: reads the object manager, opens nothing) is
    not `\Device\HarddiskVolume*` or `\Device\CdRom*`. A `\??\X:\dir` alias (`subst`) is walked
    again from its target so the components it hides are checked; every other device
    (`\Device\Mup`, the redirectors, an unresolved letter) is refused. This replaces the
    `GetDriveTypeW` check, which can open the file system;
  - a **reparse point other than a symbolic link or a mount point** (an app execution alias, say),
    decided by the pure, unit-tested `classify_reparse(attributes, tag)` from `lstat`'s
    `st_file_attributes` and `st_reparse_tag`. Cloud placeholders (`IO_REPARSE_TAG_CLOUD*`) count as
    plain only when none of `RECALL_ON_OPEN`, `RECALL_ON_DATA_ACCESS`, `OFFLINE` is set (opening an
    unhydrated one downloads it);
  - more than 40 links or aliases (a loop).

  `\\?\C:\...` is a local drive path and is accepted.
- `open_local(path)` (same module) opens the resolved file and, before anything is read, asks
  `GetFinalPathNameByHandleW` (NT form) where the handle really is. The handle is returned only if
  that is the resolved target on a local volume; otherwise it is closed unread.
- `backend/api/routes/face_search.py`: a JSON `{"path": ...}` query goes through `open_local`. A path
  that leads off the computer is `400 QUERY_PATH_NOT_LOCAL` ("A picture on another computer or a
  network drive cannot be searched by its path…"), without echoing the path. Before, only a path
  that began with `\\` was refused (`QUERY_IMAGE_UNREADABLE`), so `Z:\` on a mapped drive, or a
  junction or symlink to a share, was read.
- Tests: `tests/unit/test_local_path.py` (95): a `probes` guard fails any call that follows a path
  (`os.stat`, `os.open`, `Path.open`, listing, `realpath`...) and records each `lstat`, and every
  network, device-name, stream and mapped-drive refusal asserts that nothing was looked at; the
  reparse classifier over every tag class; an app execution alias and cloud placeholders (on disk and
  not) through a faked `lstat`; the DOS-device classifier; `subst` aliases (also tried for real by
  hand: `V:` over a temp folder) over a plain folder, a link to a share, a mapped drive and in a
  loop; real junctions and symlinks; `open_local` against a real handle and, closed unread, a
  handle on a share, on another volume, with no answer, and a link swapped in after the check (the
  race, deterministically). `tests/integration/test_api_face_search.py`: the network forms answer
  `QUERY_PATH_NOT_LOCAL`, a symlinked file and folder to a share are refused while a junction to a
  local folder still searches, and a new test asserts `Path.open` and `os.stat` are never reached
  for an extended path to NUL, `CON`, `COM1.txt`, a stream and a non-local drive.

## Why

Issue #174 and the owner's locked decision on it (2026-10-14): network paths may be read only when
the user has approved them (per-user opt-in roots or shares), unapproved remote hosts are denied
**before any outbound access**, the effective target is validated rather than the submitted string,
device namespaces are rejected. No network root can be approved yet, so the built behaviour is the
policy's default: every network target is refused. The Codex review of the first version found the
gaps closed here (device names made by normalisation, other reparse types, `subst` drives, the
check-to-open race).

## Decisions

- **Default deny, not the opt-in.** The opt-in configuration (where the approved roots live, how the
  user approves one, the screen) and the bounded, cancellable network read the decision requires
  (point 6: a thread timeout does not stop an outstanding SMB read) are a larger, separate piece;
  until they exist, refusing all network targets is the only behaviour the decision allows.
  Confirmed by the owner on 2026-10-16 ("Okay, I confirm on all 4": refuse every network target by
  default, no approved-roots opt-in yet).
- **Links are resolved by reading them, never by `Path.resolve()`:** `resolve` opens the target
  (`GetFinalPathNameByHandle`), which would contact the share while deciding.
- **Residual window, documented:** between the walk and the open, a link planted along the path is
  followed by the open itself, which could contact a share. The check afterwards guarantees that
  nothing is read from anywhere but the resolved local file. Closing it fully needs a walk through
  retained directory handles with no-follow semantics (`NtCreateFile`); not built.
- **Conservative refusals:** a volume mount point, any drive whose device is not a local volume
  (third-party virtual disks included) and a path using 8.3 short names (Windows reports the long
  name, so the handle check cannot match) are refused rather than looked into. Case is ignored.
- **Scope:** face search by path only, as the issue says. A referenced import from a network share is
  a different trust question (the user's own photographs on a NAS) and is listed below.

## Verification

- `uv run pytest -q tests/unit/test_local_path.py tests/integration/test_api_face_search.py`, then
  the full backend gate with coverage; see the PR for the results on the exact head.
- Not verified: a real mapped network drive or a real cloud placeholder (no share or sync client on
  this machine or in CI).

## Open issues / follow-ups

- #174 stays open for the approved network roots (configuration and screen), the bounded network
  read, and the retained-handle walk that closes the residual window.
- Referenced import (`inspect_referenced_file`) resolves with `Path.resolve(strict=True)`, which
  follows a link to a share: decide whether a referenced original may live on a network share.
