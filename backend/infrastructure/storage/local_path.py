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

The whole way is walked by retained handles, for the check as well as for the open: the volume (by
the NT device name the drive letter was checked against, or by the `UNC` alias of an approved share)
and then each component relative to the handle before it, every one opened with
`FILE_OPEN_REPARSE_POINT` so that no link or junction is ever followed. A link met on the way is
read from its open handle and judged by where it leads; any other reparse point is refused. A link
planted while this runs therefore cannot redirect a lookup or the open anywhere, and a drive letter
remapped after the check cannot either. `open_local` keeps the last handle, checks it to be a plain
disk file (not a directory, a pipe or a device) and that Windows places it where the resolved
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
_DIRECTORY = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)

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
    _FSCTL_GET_REPARSE_POINT = 0x900A8
    # access: list or read data, read attributes, synchronize (the same for a folder and a file)
    _ACCESS = 0x1 | 0x80 | 0x100000
    _SHARE_ALL = 0x7  # (the walk must not stop anyone else from using what it passes through)
    _OPEN_EXISTING = 0x1  # FILE_OPEN
    # options: never follow a reparse point, plain synchronous I/O; neither "folder" nor "file" is
    # demanded, so a link (which may be either) is opened itself and can be read
    _OPTIONS = 0x200000 | 0x20
    _CASE_INSENSITIVE = 0x40
    _GONE = tuple(
        ctypes.c_long(status).value
        for status in (0xC0000034, 0xC000003A, 0xC0000039, 0xC0000103)  # name, path, not a folder
    )

    _kernel32.DeviceIoControl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    _kernel32.DeviceIoControl.restype = ctypes.c_int

    def _nt_create(parent: int | None, name: str) -> int:
        """Open one step by NtCreateFile: `name` is absolute (`\\Device\\...`, `\\??\\UNC\\...`)
        when there is no `parent`, else one component of it. Never follows a reparse point.
        A name that is not there is a FileNotFoundError; any other failure is an OSError."""
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
            _ACCESS,
            ctypes.byref(attributes),
            ctypes.byref(status_block),
            None,
            0,
            _SHARE_ALL,
            _OPEN_EXISTING,
            _OPTIONS,
            None,
            0,
        )
        if status in _GONE:
            raise FileNotFoundError(2, "Not there")
        if status < 0:
            raise ctypes.WinError(_ntdll.RtlNtStatusToDosError(status))
        return int(handle.value or 0)

    def _attributes(handle: int) -> tuple[int, int] | None:
        """The opened entry's own (attributes, reparse tag), or None if Windows will not say."""
        info = _AttributeTag()
        if not _kernel32.GetFileInformationByHandleEx(
            handle, _FILE_ATTRIBUTE_TAG_INFO, ctypes.byref(info), ctypes.sizeof(info)
        ):
            return None
        return info.FileAttributes, info.ReparseTag

    def _reparse_data(handle: int) -> bytes | None:
        """The raw reparse data of an open link (`FSCTL_GET_REPARSE_POINT`), or None."""
        buffer = ctypes.create_string_buffer(16 * 1024)
        returned = ctypes.c_uint32()
        if not _kernel32.DeviceIoControl(
            handle,
            _FSCTL_GET_REPARSE_POINT,
            None,
            0,
            buffer,
            len(buffer),
            ctypes.byref(returned),
            None,
        ):
            return None
        return buffer.raw[: returned.value]

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

    def _nt_create(parent: int | None, name: str) -> int:
        raise OSError("handle walks need Windows")

    def _attributes(handle: int) -> tuple[int, int] | None:
        return None

    def _reparse_data(handle: int) -> bytes | None:
        return None

    def _file_type(handle: int) -> int:
        return 0

    def _close(handle: int) -> None:
        return None

    def _as_file(handle: int) -> BinaryIO:
        raise OSError("handle walks need Windows")

    _FILE_TYPE_DISK = 1


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


def parse_reparse(data: bytes) -> tuple[str, bool] | None:
    """(the link's target name, whether it is relative) from the raw reparse data of a symbolic
    link or a mount point; None for anything else or for data that does not hold together."""
    if len(data) < 8:
        return None
    tag = int.from_bytes(data[0:4], "little")
    if tag not in (_TAG_SYMLINK, _TAG_MOUNT_POINT):
        return None
    base = 8 + (12 if tag == _TAG_SYMLINK else 8)
    offset = int.from_bytes(data[8:10], "little")
    length = int.from_bytes(data[10:12], "little")
    raw = data[base + offset : base + offset + length]
    if len(data) < base or len(raw) != length or length == 0 or length % 2:
        return None
    relative = tag == _TAG_SYMLINK and bool(int.from_bytes(data[16:20], "little") & 1)
    try:
        return raw.decode("utf-16-le"), relative
    except UnicodeDecodeError:
        return None


def _link_text(name: str, relative: bool, folder: str) -> str | None:
    """A link's target as text to resolve again: relative ones from the folder holding the link,
    NT-form ones (`\\??\\C:\\x`, `\\??\\UNC\\server\\share`) in plain form; None for any other
    NT name (a volume GUID, a device)."""
    if relative:
        return os.path.join(folder, name)
    if name.upper().startswith(_UNC_ALIAS.upper()):
        return "\\\\" + name[len(_UNC_ALIAS) :]
    if name.startswith("\\??\\"):
        rest = name[4:]
        drive, _ = ntpath.splitdrive(rest)
        return rest if len(drive) == 2 and drive[1] == ":" else None
    return None


class _Follow:
    """The walk met a link and read where it leads; resolve that text again."""

    def __init__(self, text: str) -> None:
        self.text = text


def _walk(
    target: Path, root: str, *, links: bool, keep: bool
) -> "tuple[Path, int | None] | _Follow | None":
    """Walk `target` below `root` by retained handles: the root, then each component opened
    relative to the handle before it, never following a link. A symbolic link or junction is read
    (never followed) and, where `links`, answered as `_Follow`; any other reparse point, or a link
    where none may be, is a refusal (None). A name that is not there ends the walk: with `keep`
    that is a FileNotFoundError, otherwise the path simply need not exist yet. With `keep`, the last
    step must be a plain disk file and its handle is returned (the caller owns it); without it
    every handle is closed. Errors other than "not there" are OSErrors with `keep`, and a refusal
    without it (an entry that cannot be examined is not walked through)."""
    parts = target.parts[1:]
    held: list[int] = []
    try:
        parent = _nt_create(None, root)
        held.append(parent)
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            try:
                child = _nt_create(parent, part)
            except FileNotFoundError:
                if keep:
                    raise
                return target, None
            except OSError:
                if keep:
                    raise
                return None
            held.append(child)
            examined = _attributes(child)
            if examined is None:
                return None
            attributes, tag = examined
            action = classify_reparse(attributes, tag)
            if action is Reparse.REFUSE:
                return None
            if action is Reparse.FOLLOW:
                data = _reparse_data(child) if links else None
                read = parse_reparse(data) if data else None
                folder = os.fspath(
                    Path(*target.parts[: index + 2]).parent
                )  # (the link's own folder)
                text = _link_text(*read, folder) if read else None
                if text is None:
                    return None
                return _Follow(os.path.join(text, *parts[index + 1 :]))
            if not last and not attributes & _DIRECTORY:
                if keep:
                    raise FileNotFoundError(2, "Not a folder")
                return target, None
            if last and keep:
                if attributes & _DIRECTORY:
                    raise IsADirectoryError(21, "A folder is not a picture")
                if _file_type(child) != _FILE_TYPE_DISK:
                    return None  # a pipe, a device
            parent = child
        if keep:
            return (target, held.pop()) if parts else None  # (a volume root is not a file)
        return target, None
    finally:
        for handle in held:
            _close(handle)


def _resolve(
    path: str | Path, approved: Approved | None, *, keep: bool
) -> tuple[Path, int | None] | None:
    """The file `path` leads to, and with `keep` its open handle (see `_walk`). None if it leads
    off this computer to anywhere `approved` does not accept, to a device, through a reparse point
    it will not follow, or through too many links. A network target is decided on text before
    anything is opened, and every local step is a no-follow handle open, so a link planted while
    this runs is read and judged, never followed."""
    text = os.fspath(path)
    for _ in range(MAX_LINKS + 1):
        parts = unc_parts(text)
        if parts is not None:  # a UNC path, however it was reached: approved, or refused unseen
            canonical = "\\\\" + "\\".join(parts)
            if approved is None or not approved(canonical):
                return None
            target = Path(canonical)
            if not keep:
                return target, None  # (decided on text: nothing is contacted to answer)
            outcome = _walk(target, _UNC_ALIAS + target.drive[2:] + "\\", links=False, keep=True)
            return None if outcome is None or isinstance(outcome, _Follow) else outcome
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
        outcome = _walk(current, alias + "\\", links=True, keep=keep)
        if isinstance(outcome, _Follow):
            text = outcome.text
            continue
        return outcome
    return None


def local_target(path: str | Path, approved: Approved | None = None) -> Path | None:
    """The file `path` leads to, links and junctions resolved: a local path, or (only when
    `approved` accepts it) a UNC path on an approved share. None if it leads off this computer to
    anywhere not approved, to a device, through a reparse point it will not follow, or through too
    many links. The file itself need not exist. A network target is decided on text alone."""
    resolved = _resolve(path, approved, keep=False)
    return resolved[0] if resolved else None


def _expected_nt_path(target: Path) -> str | None:
    """The NT name of a resolved local file, or None if its drive is not a local volume."""
    kind, device = classify_dos_device(_query_dos_device(target.drive))
    return device + os.fspath(target)[len(target.drive) :] if kind is DosDevice.LOCAL else None


def open_local(path: str | Path, approved: Approved | None = None) -> BinaryIO | None:
    """The file `path` leads to, opened for reading, or None if it leads off this computer to
    anywhere `approved` does not accept (or is not a plain file).

    Raises OSError when the file cannot be opened (FileNotFoundError when it is not there,
    IsADirectoryError for a folder). The whole way is walked by retained no-follow handles, and a
    handle is returned only once Windows says it is where the resolved target says, so nothing is
    read before that is known."""
    resolved = _resolve(path, approved, keep=True)
    if resolved is None:
        return None
    target, handle = resolved
    assert handle is not None  # (`keep` always answers a handle)
    opened = _as_file(handle)
    if target.drive.startswith("\\\\"):
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
