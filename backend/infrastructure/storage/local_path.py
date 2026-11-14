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

Owner decision 2026-10-14 (on #174, locked): a network location may be read only when the user has
approved it. `local_target(path, approved)` therefore also answers a UNC path, when the effective
target (a UNC text, a mapped drive's share, a subst of one, or a link whose target is one) is inside
a root `approved` accepts; the answer is decided on text, before any outbound access, and every
unapproved network target stays refused. Mapped drives are read from the object manager
(`QueryDosDeviceW`), never contacted. Links on a remote share are not walked: the open refuses them.

`open_local` opens the target by a walk of retained handles: the volume (by the NT device name
the drive letter was checked against, or by the `UNC` alias of an approved share)
and then each component relative to the handle before it, every one opened with
`FILE_OPEN_REPARSE_POINT` so that no link or junction is ever followed, and refused if it is a
reparse point. A link planted after the check therefore cannot redirect the open anywhere, and a
drive letter remapped after the check cannot either. The file handle is then checked to be a plain
disk file (not a directory, a pipe or a device), and that Windows places it where the resolved
target says (the NT name on a local volume; for a share a name still inside an approved root).
Nothing is read before all of that holds.
"""

import ntpath
import os
import re
import stat
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import BinaryIO

from backend.infrastructure.storage.unc import is_device_component, unc_parts

Approved = Callable[[str], bool]  # a UNC path (canonical form) -> may it be read?

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


_MAPPED_DRIVE = re.compile(
    r"\\Device\\(?:Mup\\;)?LanmanRedirector\\;[A-Za-z]:[0-9A-Fa-f]+\\(?P<share>[^\\].*)",
    re.IGNORECASE,
)
_UNC_ALIAS = "\\??\\UNC\\"


def unc_of_device(device: str | None) -> str | None:
    """The UNC path a drive letter's DOS device stands for, when it is an SMB mapping
    (`\\Device\\LanmanRedirector\\;Z:<id>\\server\\share[\\folder]`, also under `\\Device\\Mup`) or
    a subst of a UNC (`\\??\\UNC\\server\\share`); else None (DFS, WebDAV, a provider unknown here).
    Text only: the connection the mapping already has is not touched."""
    if not device:
        return None
    mapped = _MAPPED_DRIVE.fullmatch(device)
    if mapped:
        return "\\\\" + mapped.group("share")
    if device.upper().startswith(_UNC_ALIAS.upper()):
        return "\\\\" + device[len(_UNC_ALIAS) :]
    return None


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

    def _final_path(descriptor: int, flags: int) -> str | None:
        try:
            handle = msvcrt.get_osfhandle(descriptor)
        except OSError:
            return None
        buffer = ctypes.create_unicode_buffer(32768)
        length = _kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), flags)
        return buffer.value if 0 < length < len(buffer) else None

    def _final_nt_path(descriptor: int) -> str | None:
        """Where an open file really is, in NT form, or None."""
        return _final_path(descriptor, _VOLUME_NAME_NT)

    def _final_unc_path(descriptor: int) -> str | None:
        """Where an open file on a share really is, as a UNC path, or None."""
        text = _final_path(descriptor, 0)  # (the DOS form, a `UNC` path under the extended prefix)
        parts = unc_parts(text) if text else None
        return "\\\\" + "\\".join(parts) if parts else None

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_wchar_p),
        )

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("Length", ctypes.c_ulong),
            ("RootDirectory", ctypes.c_void_p),
            ("ObjectName", ctypes.POINTER(_UnicodeString)),
            ("Attributes", ctypes.c_ulong),
            ("SecurityDescriptor", ctypes.c_void_p),
            ("SecurityQualityOfService", ctypes.c_void_p),
        )

    class _IoStatus(ctypes.Structure):
        _fields_ = (("Status", ctypes.c_void_p), ("Information", ctypes.c_void_p))

    class _AttributeTag(ctypes.Structure):  # FILE_ATTRIBUTE_TAG_INFO
        _fields_ = (("FileAttributes", ctypes.c_uint32), ("ReparseTag", ctypes.c_uint32))

    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatus),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    _ntdll.NtCreateFile.restype = ctypes.c_long
    _ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    _ntdll.RtlNtStatusToDosError.restype = ctypes.c_ulong
    _kernel32.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _kernel32.GetFileInformationByHandleEx.restype = ctypes.c_int
    _kernel32.GetFileType.argtypes = [ctypes.c_void_p]
    _kernel32.GetFileType.restype = ctypes.c_uint32
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _FILE_ATTRIBUTE_TAG_INFO = 9
    _FILE_TYPE_DISK = 1
    # access: list/traverse or read data, read attributes, synchronize
    _DIRECTORY_ACCESS = 0x1 | 0x20 | 0x80 | 0x100000
    _FILE_ACCESS = 0x1 | 0x80 | 0x100000
    _SHARE_ALL = 0x7  # (the walk must not stop anyone else from using what it passes through)
    _OPEN_EXISTING = 0x1  # FILE_OPEN
    # options: directory or non-directory, never follow a reparse point, plain synchronous I/O
    _DIRECTORY_OPTIONS = 0x1 | 0x200000 | 0x20
    _FILE_OPTIONS = 0x40 | 0x200000 | 0x20
    _CASE_INSENSITIVE = 0x40
    _STATUS_FILE_IS_A_DIRECTORY = ctypes.c_long(0xC00000BA).value

    def _nt_create(parent: int | None, name: str, *, directory: bool) -> int:
        """Open one step by NtCreateFile: `name` is absolute (`\\Device\\...`, `\\??\\UNC\\...`)
        when there is no `parent`, else one component of it. Never follows a reparse point.
        Raises OSError (FileNotFoundError and friends from the status) when the step fails."""
        length = len(name) * 2
        text = _UnicodeString(length, length + 2, name)
        attributes = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            parent,
            ctypes.pointer(text),
            _CASE_INSENSITIVE,
            None,
            None,
        )
        handle = ctypes.c_void_p()
        status_block = _IoStatus()
        status = _ntdll.NtCreateFile(
            ctypes.byref(handle),
            _DIRECTORY_ACCESS if directory else _FILE_ACCESS,
            ctypes.byref(attributes),
            ctypes.byref(status_block),
            None,
            0,
            _SHARE_ALL,
            _OPEN_EXISTING,
            _DIRECTORY_OPTIONS if directory else _FILE_OPTIONS,
            None,
            0,
        )
        if status == _STATUS_FILE_IS_A_DIRECTORY:
            raise IsADirectoryError(21, "A folder is not a picture")
        if status < 0:
            raise ctypes.WinError(_ntdll.RtlNtStatusToDosError(status))
        return int(handle.value or 0)

    def _plain(handle: int) -> bool:
        """The opened entry itself is not a reparse point (a cloud file on disk excepted)."""
        info = _AttributeTag()
        if not _kernel32.GetFileInformationByHandleEx(
            handle, _FILE_ATTRIBUTE_TAG_INFO, ctypes.byref(info), ctypes.sizeof(info)
        ):
            return False
        return classify_reparse(info.FileAttributes, info.ReparseTag) is Reparse.PLAIN

    def _file_type(handle: int) -> int:
        return int(_kernel32.GetFileType(handle))

    def _close(handle: int) -> None:
        _kernel32.CloseHandle(handle)

    def _as_file(handle: int) -> BinaryIO:
        """The handle as a buffered binary file, which now owns (and closes) it."""
        try:
            return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb")
        except OSError:
            _close(handle)
            raise

else:  # pragma: no cover - the suite runs on Windows; this keeps the module importable elsewhere

    def _query_dos_device(drive: str) -> str | None:
        return None  # ponytail: POSIX network mounts are not detected; add a statfs check if needed

    def _final_nt_path(descriptor: int) -> str | None:
        return None

    def _final_path(descriptor: int, flags: int) -> str | None:
        return None

    def _final_unc_path(descriptor: int) -> str | None:
        return None

    def _nt_create(parent: int | None, name: str, *, directory: bool) -> int:
        raise OSError("handle walks need Windows")

    def _plain(handle: int) -> bool:
        return False

    def _file_type(handle: int) -> int:
        return 0

    def _close(handle: int) -> None:
        return None

    def _as_file(handle: int) -> BinaryIO:
        raise OSError("handle walks need Windows")

    _FILE_TYPE_DISK = 1

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


def local_target(path: str | Path, approved: Approved | None = None) -> Path | None:
    """The file `path` leads to, links and junctions resolved: a local path, or (only when
    `approved` accepts it) a UNC path on an approved share. None if it leads off this computer to
    anywhere not approved, to a device, through a reparse point it will not follow, or through too
    many links. The file itself need not exist. A network target is decided on text alone."""
    text = os.fspath(path)
    for _ in range(MAX_LINKS + 1):
        parts = unc_parts(text)
        if parts is not None:  # a UNC path, however it was reached: approved, or refused unseen
            canonical = "\\\\" + "\\".join(parts)
            return Path(canonical) if approved is not None and approved(canonical) else None
        local = _local_text(text)
        if local is None:
            return None
        normal = os.path.abspath(local)  # (.. is collapsed by name, as Windows does)
        if normal.startswith("\\\\"):
            return None  # normalising built a device or network form (\\?\C:\NUL -> \\.\NUL)
        current = Path(normal)
        device = _query_dos_device(current.drive)
        kind, alias = classify_dos_device(device)
        if kind is DosDevice.REFUSE:
            share = unc_of_device(device)  # an SMB mapping: its share, decided on text
            if share is None:
                return None
            text = os.path.join(share, *current.parts[1:])
            continue
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


def _is_network(target: Path) -> bool:
    return target.drive.startswith("\\\\")


def _root_name(target: Path) -> str | None:
    """The name the volume or share is opened by, with its closing separator: the device the drive
    letter classified as local (a letter remapped later changes nothing), or the share's alias."""
    if _is_network(target):
        return "\\??\\UNC\\" + target.drive[2:] + "\\"
    kind, device = classify_dos_device(_query_dos_device(target.drive))
    return device + "\\" if kind is DosDevice.LOCAL else None


def _open_walk(target: Path) -> int | None:
    """Open `target` by retained handles, no link ever followed: the root, then each component
    relative to the handle before it. None if any step is a reparse point, a folder where the file
    should be (or the reverse), not a plain disk file at the end. Raises OSError when a step cannot
    be opened (including a missing file)."""
    root = _root_name(target)
    if root is None:
        return None
    parts = target.parts[1:]
    held: list[int] = []
    try:
        parent = _nt_create(None, root, directory=True)
        held.append(parent)
        if not _plain(parent):
            return None
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            child = _nt_create(parent, part, directory=not last)
            held.append(child)
            if not _plain(child) or (last and _file_type(child) != _FILE_TYPE_DISK):
                return None
            parent = child
        if not parts:
            return None  # (a volume root is not a file)
        return held.pop()
    finally:
        for handle in held:
            _close(handle)


def open_local(path: str | Path, approved: Approved | None = None) -> BinaryIO | None:
    """The file `path` leads to, opened for reading, or None if it leads off this computer to
    anywhere `approved` does not accept (or is not a plain file).

    Raises OSError when the file cannot be opened. A handle is returned only once it was opened
    with no link followed and Windows says it is where the resolved target says, so nothing is read
    before that is known."""
    target = local_target(path, approved)
    if target is None:
        return None
    network = _is_network(target)
    handle = _open_walk(target)
    if handle is None:
        return None
    opened = _as_file(handle)
    if network:
        final = _final_unc_path(opened.fileno())
        trusted = final is not None and approved is not None and approved(final)
    else:
        final_nt = _final_nt_path(opened.fileno())
        expected = _expected_nt_path(target)
        trusted = (
            final_nt is not None and expected is not None and final_nt.upper() == expected.upper()
        )
    if not trusted:
        opened.close()
        return None
    return opened
