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
wildcards, a stream, a reserved device name and `..` are refused.
"""

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.infrastructure.storage.local_path import is_device_component

_EXTENDED_UNC = "\\\\?\\UNC\\"
FILE_NAME = "network-roots.json"


class NetworkRootInvalidError(ValueError):
    """The text is not a share or a folder on a share that can be approved."""


class NetworkRootNotFoundError(LookupError):
    """No approved root has that id."""


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
    if not text.startswith("\\\\") or text.startswith("\\\\.\\") or text.startswith("\\\\?\\"):
        return None
    parts = [part for part in text[2:].split("\\") if part not in ("", ".")]
    if len(parts) < 2 or any(_unsafe(part) for part in parts):
        return None
    if "@" in parts[0]:
        return None  # `server@SSL` and `server@8080` are WebDAV: an HTTP connection, not SMB
    return tuple(parts)


def _unsafe(part: str) -> bool:
    return (
        part == ".."
        or part[-1] in " ."  # Windows drops them: two spellings of one name
        or any(ord(char) < 32 for char in part)
        or is_device_component(part)  # wildcards, a stream, a device name
    )


def key_of(parts: tuple[str, ...]) -> str:
    return "\\".join(part.upper() for part in parts)


def is_inside(parts: tuple[str, ...], root_key: str) -> bool:
    """Whether the path (as components) is the approved root or lies below it."""
    wanted = root_key.split("\\")
    return len(parts) >= len(wanted) and [p.upper() for p in parts[: len(wanted)]] == wanted


def _root_of(path: str, approved_at: str) -> NetworkRoot:
    parts = unc_parts(path)
    if parts is None:
        raise NetworkRootInvalidError("not a share or a folder on a share")
    key = key_of(parts)
    return NetworkRoot(
        id=hashlib.sha256(key.encode()).hexdigest()[:16],
        path="\\\\" + "\\".join(parts),
        approved_at=approved_at,
    )


class NetworkRoots:
    """The approved roots, kept in one file. Safe to share between threads."""

    def __init__(self, directory: Path) -> None:
        self._file = directory / FILE_NAME
        self._lock = threading.Lock()

    def approved(self) -> list[NetworkRoot]:
        with self._lock:
            return self._read()

    def add(self, path: str, *, now: datetime) -> NetworkRoot:
        """Approve a root. Asking again for one already approved keeps its first approval."""
        root = _root_of(path, now.isoformat())
        with self._lock:
            held = self._read()
            for one in held:
                if one.id == root.id:
                    return one
            self._write([*held, root])
        return root

    def revoke(self, root_id: str) -> None:
        with self._lock:
            held = self._read()
            kept = [one for one in held if one.id != root_id]
            if len(kept) == len(held):
                raise NetworkRootNotFoundError(root_id)
            self._write(kept)

    def approves(self, path: str) -> bool:
        """Whether `path` (a UNC path) is an approved root or inside one. Text only."""
        parts = unc_parts(path)
        if parts is None:
            return False
        return any(is_inside(parts, key_of(unc_parts(one.path) or ())) for one in self.approved())

    def _read(self) -> list[NetworkRoot]:
        try:
            held = json.loads(self._file.read_text(encoding="utf-8"))
            return [_root_of(item["path"], item["approved_at"]) for item in held["roots"]]
        except (OSError, ValueError, KeyError, TypeError):
            return []  # nothing approved, or a file that cannot be trusted: default deny

    def _write(self, roots: list[NetworkRoot]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        partial = self._file.with_name(f"{FILE_NAME}.partial")
        body = {"roots": [{"path": r.path, "approved_at": r.approved_at} for r in roots]}
        partial.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(partial, self._file)
