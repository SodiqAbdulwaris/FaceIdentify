"""The network locations the user has approved for face search by path (issue #174).

Owner decision 2026-10-14 (locked): a picture on another computer may be read only from a share
or folder the user approved by name. This module holds that list and decides, from text alone,
whether a UNC path lies inside it. It never contacts a host: not to add a root, not to compare.
The list is machine-local state (one JSON file under the local state root, replaced atomically),
because an approval is about this computer's network and its user, and must not travel with a
library that is copied to another machine. No credential is ever stored: only the share's name.

A root is a share (server and share name) or a folder on one. It is shown in one form (backslashes,
no trailing separator) and compared in another (upper case, component by component), so
`//SERVER/Share/`, the extended UNC form and a trailing dot component all name one root, and
`share2` is not inside `share`. Device namespaces, a missing share, a WebDAV host (`server@SSL`),
wildcards, a stream, a reserved device name, `..`, the WebDAV share name, and any administrative or
hidden share (a name ending in `$`: `C$`, `IPC$`) are refused. Names are folded by ASCII case only,
so a root can under-approve a non-ASCII spelling but never over-approve one.

A caller that goes on to open a path must open the canonical form (`unc_parts` rebuilt), never the
text it was given.
"""

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.infrastructure.storage.local_path import is_device_component

_EXTENDED_UNC = "\\\\?\\UNC\\"
FILE_NAME = "network-roots.json"
_LOCK = threading.Lock()  # one per process: every NetworkRoots (one is built per request) shares it
# ponytail: one backend process owns a local state root (the library lock); a second process would
# need a file lock around read-modify-write.


class NetworkRootInvalidError(ValueError):
    """The text is not a share or a folder on a share that can be approved."""


class NetworkRootNotFoundError(LookupError):
    """No approved root has that id."""


class NetworkRootsUnreadableError(OSError):
    """The file exists but cannot be read or trusted. Nothing is approved while it is so, and
    nothing is written over it (that would silently drop every earlier approval)."""


@dataclass(frozen=True)
class NetworkRoot:
    id: str  # a digest of the key: the same root always has the same id
    path: str  # `\\server\share\folder`, as the user wrote it, with backslashes
    approved_at: str  # ISO 8601, UTC


def unc_parts(text: str) -> tuple[str, ...] | None:
    """The components of a conventional UNC path (`server`, `share`, folders...), or None when the
    text is not one (a drive path, a device namespace, an empty part, a `..`, or a part Windows
    would read as something else). Pure: nothing is opened. The extended
    UNC form is the same path."""
    text = text.replace("/", "\\")
    if text.upper().startswith(_EXTENDED_UNC):
        text = "\\\\" + text[len(_EXTENDED_UNC) :]
    if not text.startswith("\\\\") or text[2:3] in ("\\", ".", "?", ""):
        return None  # (a third separator, `\\.\` and `\\?\` are device or namespace forms)
    parts = [part for part in text[2:].split("\\") if part not in ("", ".")]
    if len(parts) < 2 or any(_unsafe(part) for part in parts):
        return None
    if "@" in parts[0]:
        return None  # `server@SSL` and `server@8080` are WebDAV: an HTTP connection, not SMB
    if parts[1].upper() == "DAVWWWROOT" or parts[1].endswith("$"):
        return None  # the WebDAV redirector's name; administrative, hidden and IPC shares
    return tuple(parts)


def _unsafe(part: str) -> bool:
    return (
        part == ".."
        or part[-1] in " ."  # Windows drops them: two spellings of one name
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in part)
        or is_device_component(part)  # wildcards, a stream, a device name
    )


def _fold(part: str) -> str:
    """ASCII case only: NTFS folds more than `str.upper` in some places and less in others, so a
    non-ASCII name is compared exactly (it can under-approve, never over-approve)."""
    return "".join(char.upper() if char.isascii() else char for char in part)


def key_of(parts: tuple[str, ...]) -> str:
    return "\\".join(_fold(part) for part in parts)


def is_inside(parts: tuple[str, ...], root_key: str) -> bool:
    """Whether the path (as components) is the approved root or lies below it."""
    wanted = root_key.split("\\")
    return len(parts) >= len(wanted) and [_fold(p) for p in parts[: len(wanted)]] == wanted


def _root_of(path: str, approved_at: str) -> NetworkRoot:
    parts = unc_parts(path)
    if parts is None:
        raise NetworkRootInvalidError("not a share or a folder on a share")
    return NetworkRoot(
        id=hashlib.sha256(key_of(parts).encode()).hexdigest()[:16],
        path="\\\\" + "\\".join(parts),
        approved_at=approved_at,
    )


class NetworkRoots:
    """The approved roots, kept in one file. Safe to share between threads."""

    def __init__(self, directory: Path) -> None:
        self._file = directory / FILE_NAME

    def approved(self) -> list[NetworkRoot]:
        """The list; `NetworkRootsUnreadableError` if the file is there and cannot be trusted."""
        with _LOCK:
            return self._read()

    def add(self, path: str, *, now: datetime) -> NetworkRoot:
        """Approve a root. Asking again for one already approved keeps its first approval."""
        root = _root_of(path, now.isoformat())
        with _LOCK:
            held = self._read()
            for one in held:
                if one.id == root.id:
                    return one
            self._write([*held, root])
        return root

    def revoke(self, root_id: str) -> None:
        with _LOCK:
            held = self._read()
            kept = [one for one in held if one.id != root_id]
            if len(kept) == len(held):
                raise NetworkRootNotFoundError(root_id)
            self._write(kept)

    def approves(self, path: str) -> bool:
        """Whether `path` (a UNC path) is an approved root or inside one. Text only. A file that
        cannot be trusted approves nothing (default deny)."""
        parts = unc_parts(path)
        if parts is None:
            return False
        try:
            held = self.approved()
        except NetworkRootsUnreadableError:
            return False
        return any(is_inside(parts, key_of(unc_parts(one.path) or ())) for one in held)

    def _read(self) -> list[NetworkRoot]:
        try:
            text = self._file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []  # nothing approved yet
        except OSError as error:
            raise NetworkRootsUnreadableError(error) from None
        try:
            items = json.loads(text)["roots"]
            found: dict[str, NetworkRoot] = {}
            for item in items:
                if not isinstance(item["approved_at"], str):
                    raise TypeError
                root = _root_of(item["path"], item["approved_at"])
                found.setdefault(root.id, root)
            return list(found.values())
        except (ValueError, KeyError, TypeError):
            raise NetworkRootsUnreadableError("the approvals file cannot be trusted") from None

    def _write(self, roots: list[NetworkRoot]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        body = {"roots": [{"path": r.path, "approved_at": r.approved_at} for r in roots]}
        descriptor, partial = tempfile.mkstemp(dir=self._file.parent, suffix=".partial")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(body, indent=1))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, self._file)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise
