"""Where does a path really lead, without going there? (issue #174)

A path that looks local can lead off this computer: a mapped network drive (`Z:\\...`), or a
symbolic link or junction anywhere along it whose target is a network share. Opening it would make
this computer reach out, and possibly authenticate, to another one. `local_target` follows the path
the way Windows would, one component at a time, but reads each link's target from the link itself
(`lstat` and `readlink` touch only the local volume), so nothing remote is contacted while it
decides. It answers the fully resolved local file, or None when any step leaves the computer: a
UNC (`\\\\server\\share`) or device (`\\\\.\\`, `\\\\?\\` other than a drive) form, a mapped network
drive, or a volume mount point (`\\\\?\\Volume{...}`), which is refused rather than looked into.

Owner decision 2026-10-14 (on #174, locked): network locations may be read only when the user has
approved them. None is approved yet (that configuration is not built), so every network target is
refused, before any outbound access.
"""

import ntpath
import os
import sys
from pathlib import Path

MAX_LINKS = 40  # (Windows itself gives up after 63 reparse points; a loop is refused here)

_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = "\\\\?\\UNC\\"


def _local_text(text: str) -> str | None:
    """The path in plain local form, or None if it names something off this computer or a device."""
    text = text.replace("/", "\\")  # (Windows reads / as \ too: //server is a network path)
    if text.upper().startswith(_EXTENDED_UNC):
        return None
    if text.startswith(_EXTENDED):
        rest = text[len(_EXTENDED) :]
        drive, _ = ntpath.splitdrive(rest)
        return rest if len(drive) == 2 and drive[1] == ":" else None  # \\?\C:\... only
    if text.startswith("\\\\"):
        return None  # UNC, \\.\ devices, named pipes
    return text


if sys.platform == "win32":
    import ctypes

    def _is_network_drive(drive: str) -> bool:
        drive_remote = 4  # DRIVE_REMOTE (GetDriveTypeW reads the mapping; it does not connect)
        return bool(drive) and ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == drive_remote

else:  # pragma: no cover - the suite runs on Windows; this keeps the module importable elsewhere

    def _is_network_drive(drive: str) -> bool:
        return (
            False  # ponytail: POSIX network mounts are not detected; add a statfs check if needed
        )


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()  # (both answer False when it cannot be examined)


def local_target(path: str | Path) -> Path | None:
    """The local file `path` leads to, links and junctions resolved, or None if it leads off this
    computer (or through too many links). The file itself need not exist."""
    text = os.fspath(path)
    for _ in range(MAX_LINKS + 1):
        local = _local_text(text)
        if local is None:
            return None
        current = Path(os.path.abspath(local))  # (.. is collapsed by name, as Windows does)
        if _is_network_drive(current.drive):
            return None
        walked = Path(current.anchor)
        parts = current.parts[1:]
        for index, part in enumerate(parts):
            walked = walked / part
            if _is_link(walked):
                target = Path(os.readlink(walked))
                if not target.is_absolute():
                    target = walked.parent / target
                text = os.fspath(target.joinpath(*parts[index + 1 :]))
                break
        else:
            return current
    return None
