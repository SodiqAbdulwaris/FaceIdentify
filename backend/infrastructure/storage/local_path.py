"""Where does a path really lead, without going there? (issue #174)

A path that looks local can lead off this computer: a mapped network drive (`Z:\\...`), a `subst`
drive that hides a junction, or a symbolic link or junction anywhere along it whose target is a
network share. Opening it would make this computer reach out, and possibly authenticate, to another
one. `local_target` follows the path the way Windows would, one component at a time, but reads each
link's target from the link itself (`FindFirstFileW` and `readlink` touch only the local volume),
so nothing remote is contacted while it decides. It answers the fully resolved local file, or None
when any step leaves the computer or cannot be shown to stay on it:

- a UNC (`\\\\server\\share`) or device (`\\\\.\\`, `\\\\?\\` other than a drive) form, also
  one that normalisation would create (`\\\\?\\C:\\NUL` becomes `\\\\.\\NUL`), a Windows reserved
  device name (`NUL`, `COM1`, `CONIN$` ... with any extension, trailing dot or space) or an
  alternate data stream, in any component;
- a drive letter whose DOS device (`QueryDosDeviceW`, which reads the object manager and opens
  nothing) is not a local volume: a `\\??\\X:\\dir` alias is walked again from its target, so the
  components it hides are checked, and only a bare `\\Device\\HarddiskVolumeN` or `\\Device\\CdRomN`
  (no folder suffix, which would hide components) is accepted;
- a reparse point other than a symbolic link or a mount point (junction), such as an app execution
  alias, or a cloud placeholder that is not on disk (opening it would download it).

`open_local` then opens the resolved file and, before anything is read, asks Windows where the open
handle really is (`GetFinalPathNameByHandleW`, NT form) and refuses unless that is the resolved
file on a local volume. Residual window: a link planted between the walk and the open is followed by
the open itself (a handle walk with no-follow semantics would close it, and is not built); the check
afterwards still guarantees that no byte is read from anywhere but the resolved local file.

Owner decision 2026-10-14 (on #174, locked): network locations may be read only when the user has
approved them. None is approved yet (that configuration is not built), so every network target is
refused, before any outbound access.
"""

import ntpath
import os
import re
import stat
import sys
from enum import Enum
from pathlib import Path
from typing import BinaryIO

MAX_LINKS = 40  # (Windows itself gives up after 63 reparse points; a loop is refused here)

_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = "\\\\?\\UNC\\"

_TAG_SYMLINK = 0xA000000C  # IO_REPARSE_TAG_SYMLINK
_TAG_MOUNT_POINT = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT (a junction)
_TAG_CLOUD = 0x9000001A  # IO_REPARSE_TAG_CLOUD .. _CLOUD_F: 0x9000?01A
_TAG_CLOUD_MASK = 0xFFFF0FFF  # (the nibble 0xF000 numbers the variants)
_RECALL = (
    getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_OPEN", 0x40000)
    | getattr(stat, "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS", 0x400000)
    | getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_VOLUME_DEVICE = re.compile(r"\\Device\\(HarddiskVolume|CdRom)\d+", re.IGNORECASE)
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
_RESERVED |= {f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789¹²³"}


class Reparse(Enum):
    PLAIN = "plain"  # nothing to follow, nothing to fear
    FOLLOW = "follow"  # a symbolic link or junction: read its target
    REFUSE = "refuse"  # any other reparse point, or a file that is not on disk


def classify_reparse(attributes: int, tag: int) -> Reparse:
    """What to do with an entry, from its own attributes and reparse tag (never followed)."""
    if not attributes & _REPARSE:
        return Reparse.PLAIN
    if tag in (_TAG_SYMLINK, _TAG_MOUNT_POINT):
        return Reparse.FOLLOW
    if tag & _TAG_CLOUD_MASK == _TAG_CLOUD and not attributes & _RECALL:
        return Reparse.PLAIN  # a cloud file that is already on this disk
    return Reparse.REFUSE


def is_device_component(part: str) -> bool:
    """A name Windows reads as a device, a stream or a search pattern, whatever follows it
    (`nul.txt`, `NUL .`, `a:b`, `*`)."""
    if any(char in part for char in ':*?<>"|'):
        return True  # an alternate data stream (and `NUL:`), or a wildcard the lookup would expand
    base = part.rstrip(" .").split(".")[0].rstrip(" ")
    return base.upper() in _RESERVED


class DosDevice(Enum):
    LOCAL = "local"
    ALIAS = "alias"
    REFUSE = "refuse"


def classify_dos_device(target: str | None) -> tuple[DosDevice, str]:
    """What a drive letter maps to, from `QueryDosDeviceW`: a local volume, an alias to walk again
    (`\\??\\C:\\base` gives `C:\\base`), or anything else (a share, a redirector, nothing)."""
    if not target:
        return DosDevice.REFUSE, ""
    if target.startswith("\\??\\"):
        rest = target[4:]
        drive, _ = ntpath.splitdrive(rest)
        if len(drive) == 2 and drive[1] == ":":
            return DosDevice.ALIAS, rest
        return DosDevice.REFUSE, ""  # \??\UNC\..., \??\Volume{...}
    if _VOLUME_DEVICE.fullmatch(target):  # (a bare volume: a suffix would hide folders)
        return DosDevice.LOCAL, target
    return DosDevice.REFUSE, ""  # \Device\Mup, \Device\LanmanRedirector, ...


if sys.platform == "win32":
    import ctypes
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    _kernel32.QueryDosDeviceW.restype = ctypes.c_uint32
    _kernel32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    _kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    _VOLUME_NAME_NT = 0x2

    class _FindData(ctypes.Structure):  # WIN32_FIND_DATAW
        _fields_ = (
            ("dwFileAttributes", ctypes.c_uint32),
            ("ftCreationTime", ctypes.c_uint32 * 2),
            ("ftLastAccessTime", ctypes.c_uint32 * 2),
            ("ftLastWriteTime", ctypes.c_uint32 * 2),
            ("nFileSizeHigh", ctypes.c_uint32),
            ("nFileSizeLow", ctypes.c_uint32),
            ("dwReserved0", ctypes.c_uint32),  # the reparse tag, when there is one
            ("dwReserved1", ctypes.c_uint32),
            ("cFileName", ctypes.c_wchar * 260),
            ("cAlternateFileName", ctypes.c_wchar * 14),
        )

    _kernel32.FindFirstFileW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_FindData)]
    _kernel32.FindFirstFileW.restype = ctypes.c_void_p
    _kernel32.FindClose.argtypes = [ctypes.c_void_p]
    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _NOT_THERE = (2, 3, 267)  # file not found, path not found, a file where a folder was expected

    def _entry(path: Path) -> tuple[int, int] | None:
        """The entry's own (attributes, reparse tag), or None if nothing is there; any other
        failure raises OSError. Unlike `os.lstat` this never reopens a reparse point it does not
        recognise with traversal (CPython does, which can start a cloud download), and it opens no
        file: it asks the parent folder about the name."""
        data = _FindData()
        handle = _kernel32.FindFirstFileW(_EXTENDED + os.fspath(path), ctypes.byref(data))
        if handle is None or handle == _INVALID_HANDLE:
            error = ctypes.get_last_error()
            if error in _NOT_THERE:
                return None
            raise ctypes.WinError(error)
        _kernel32.FindClose(handle)
        return data.dwFileAttributes, data.dwReserved0

    def _query_dos_device(drive: str) -> str | None:
        """The current mapping of a drive such as `C:`, or None. Opens nothing."""
        if not drive:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        written = _kernel32.QueryDosDeviceW(drive, buffer, len(buffer))
        return buffer.value if written else None  # (the first entry is the current mapping)

    def _final_nt_path(descriptor: int) -> str | None:
        """Where an open file really is, as `\\Device\\HarddiskVolume3\\dir\\file`, or None."""
        try:
            handle = msvcrt.get_osfhandle(descriptor)
        except OSError:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        length = _kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), _VOLUME_NAME_NT)
        return buffer.value if 0 < length < len(buffer) else None

else:  # pragma: no cover - the suite runs on Windows; this keeps the module importable elsewhere

    def _query_dos_device(drive: str) -> str | None:
        return None  # ponytail: POSIX network mounts are not detected; add a statfs check if needed

    def _final_nt_path(descriptor: int) -> str | None:
        return None

    def _entry(path: Path) -> tuple[int, int] | None:
        return None


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


def _readlink(link: Path) -> str:
    target = Path(os.readlink(link))
    return os.fspath(target if target.is_absolute() else link.parent / target)


def local_target(path: str | Path) -> Path | None:
    """The local file `path` leads to, links and junctions resolved, or None if it leads off this
    computer, to a device, through a reparse point it will not follow, or through too many links.
    The file itself need not exist."""
    text = os.fspath(path)
    for _ in range(MAX_LINKS + 1):
        local = _local_text(text)
        if local is None:
            return None
        normal = os.path.abspath(local)  # (.. is collapsed by name, as Windows does)
        if normal.startswith("\\\\"):
            return None  # normalising built a device or network form (\\?\C:\NUL -> \\.\NUL)
        current = Path(normal)
        kind, alias = classify_dos_device(_query_dos_device(current.drive))
        if kind is DosDevice.REFUSE:
            return None
        if kind is DosDevice.ALIAS:  # a subst drive: its target's components are checked too
            text = os.path.join(alias, *current.parts[1:])
            continue
        if any(is_device_component(part) for part in current.parts[1:]):
            return None
        walked = Path(current.anchor)
        parts = current.parts[1:]
        for index, part in enumerate(parts):
            walked = walked / part
            try:
                entry = _entry(walked)  # (the entry itself, never what it points at)
            except OSError:
                return None  # an entry that cannot be examined is not walked through
            if entry is None:
                continue  # nothing there (yet)
            action = classify_reparse(*entry)
            if action is Reparse.REFUSE:
                return None
            if action is Reparse.FOLLOW:
                text = os.path.join(_readlink(walked), *parts[index + 1 :])
                break
        else:
            return current
    return None


def _expected_nt_path(target: Path) -> str | None:
    """The NT name of a resolved local file, or None if its drive is not a local volume."""
    kind, device = classify_dos_device(_query_dos_device(target.drive))
    return device + os.fspath(target)[len(target.drive) :] if kind is DosDevice.LOCAL else None


def open_local(path: str | Path) -> BinaryIO | None:
    """The file `path` leads to, opened for reading, or None if it leads off this computer.

    Raises OSError when the file cannot be opened. A handle is returned only once Windows says it
    is the resolved file on a local volume, so nothing is read before that is known."""
    target = local_target(path)
    if target is None:
        return None
    handle = target.open("rb")
    final = _final_nt_path(handle.fileno())
    expected = _expected_nt_path(target)
    if final is None or expected is None or final.upper() != expected.upper():
        handle.close()
        return None
    return handle
