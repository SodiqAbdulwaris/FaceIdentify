"""Inspecting external, user-owned files for a REFERENCED import.

API and Contracts.md §57: "inspect external file → validate → ... collect fingerprint metadata",
all before the short transaction that records the Artifact. This module only reads: it never
writes to, moves or deletes an external file (§52: "The application never deletes REFERENCED
originals"), and it knows nothing about the database.
"""

from dataclasses import dataclass
from pathlib import Path

from backend.infrastructure.storage.files import StoredBytes, digest_path
from backend.infrastructure.storage.layout import StorageRoots


class ReferencedFileError(ValueError):
    """The file cannot be referenced: relative, unreadable, not a file, or in the app's roots."""


@dataclass(frozen=True)
class ReferencedFile:
    """An external file as inspected: its resolved location and content fingerprint."""

    path: Path
    stored: StoredBytes


def inspect_referenced_file(path: Path, roots: StorageRoots) -> ReferencedFile:
    """Validate and fingerprint an external file (hash and size).

    The location is resolved once, so a link or 8.3 alias is recorded as the real file it names.
    A file inside the library or machine-local root is refused: those trees belong to this
    application, and a "referenced" file there would be treated as a managed orphan.
    """
    if not path.is_absolute():
        raise ReferencedFileError(f"a referenced file needs an absolute path: {path}")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ReferencedFileError(f"not a file: {path}")
        for root in (roots.library_root, roots.local_state_root):
            if resolved.is_relative_to(root.resolve()):
                raise ReferencedFileError(f"inside the application's own storage: {path}")
        before = resolved.stat()
        stored = digest_path(resolved)
        after = resolved.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ReferencedFileError(f"{path} changed while it was being read")
        # ponytail: the file can still change after this check and before the caller's commit;
        # that is the same as changing any time later, which `reverify_referenced_artifact` finds.
        return ReferencedFile(resolved, stored)
    except (OSError, RuntimeError) as error:  # RuntimeError: a symlink or junction loop
        raise ReferencedFileError(f"cannot read {path}: {error}") from error
