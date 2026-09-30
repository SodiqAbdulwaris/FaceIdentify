"""Temporary job workspaces under machine-local `temp/jobs/<job id>/`.

IMPLEMENTATION_ARCHITECTURE.md §16.5: subsystems "may manipulate temporary computational files only
within controlled allocated workspaces". A workspace holds disposable, reconstructable files
(decoded frames, crops, intermediates), never authoritative bytes, so it lives in the
machine-local root (tech-stack.md §15), not the library.

The manager owns only directories it made itself: a real directory (never a link, junction, mount
point or any other reparse point) named `<32 lower-case hex job id>` and carrying the ownership
marker it writes on allocation. Anything else under `temp/jobs/` is not its to delete. Deciding
*which* jobs are live is the caller's (it needs the database); PERSISTENCE_IMPLEMENTATION.md §28:
"remove only application-owned workspace after verifying no live run needs it". This module knows
nothing about the database.

ponytail: a path is checked and then deleted, so a workspace swapped for a link in between would be
followed. The directory is machine-local and writable only by the current user, who can already do
anything this process can, so a handle-based deleter is not worth its complexity. Revisit if
workspaces ever move somewhere other users can write.
"""

import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path

from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.plain import is_plain_directory, is_plain_file

WORKSPACE_SUBDIRECTORIES = ("decode", "frames", "crops", "intermediate")
OWNERSHIP_MARKER = ".faceidentify-workspace"
_NAME = re.compile(r"[0-9a-f]{32}")


class WorkspaceError(Exception):
    """The path is not a workspace this manager may use or delete."""


def _clear_read_only_and_retry(
    function: Callable[[str], object], path: str, error: BaseException
) -> None:
    """`rmtree` hook: a read-only file (copied from a read-only source) is ours to remove, but a
    file that is locked stays an error."""
    if isinstance(error, PermissionError) and is_plain_file(Path(path)):
        os.chmod(path, stat.S_IWRITE)
        function(path)
    else:
        raise error


@dataclass
class WorkspaceCleanup:
    removed: list[uuid.UUID] = field(default_factory=list)
    kept: list[uuid.UUID] = field(default_factory=list)  # a live job still needs it
    # Entries under temp/jobs/ this manager did not create (or a link posing as a workspace).
    unowned: list[str] = field(default_factory=list)
    # Owned, not live, but could not be removed (a locked file); retried on the next cleanup.
    failed: list[tuple[uuid.UUID, str]] = field(default_factory=list)


class WorkspaceManager:
    def __init__(self, roots: StorageRoots) -> None:
        self.root = roots.local_state_root / "temp" / "jobs"

    def path_for(self, job_id: uuid.UUID) -> Path:
        return self.root / job_id.hex

    def allocate(self, job_id: uuid.UUID) -> Path:
        """Create the job's workspace with its standard subdirectories. Idempotent, so a retried or
        resumed job gets its existing workspace back, files included.

        Refuses an existing entry of that name that is a link or some other reparse point, or a
        directory with contents this manager did not mark as its own, instead of writing into it.
        An existing *empty* directory is adopted (a crash between creating it and marking it).
        """
        path = self.path_for(job_id)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError:
            if not is_plain_directory(path):
                raise WorkspaceError(
                    f"{path.name} is not a directory this manager may use"
                ) from None
            if not self._is_marked(path) and any(path.iterdir()):
                raise WorkspaceError(
                    f"{path.name} exists but was not made by this manager"
                ) from None
        (path / OWNERSHIP_MARKER).touch()
        for name in WORKSPACE_SUBDIRECTORIES:
            (path / name).mkdir(parents=True, exist_ok=True)
        return path

    def release(self, job_id: uuid.UUID) -> None:
        """Remove the job's workspace and everything in it. Idempotent. Never follows a link out of
        the workspace, and refuses anything that is not a workspace this manager made."""
        path = self.path_for(job_id)
        if not os.path.lexists(path):
            return
        if not self._is_workspace(path):
            raise WorkspaceError(f"{path.name} is not a workspace this manager made")
        shutil.rmtree(path, onexc=_clear_read_only_and_retry)

    def existing(self) -> list[uuid.UUID]:
        """The job ids that currently have a workspace directory."""
        if not self.root.is_dir():
            return []
        return sorted(
            uuid.UUID(hex=entry.name) for entry in self.root.iterdir() if self._is_workspace(entry)
        )

    @staticmethod
    def _is_marked(entry: Path) -> bool:
        return is_plain_file(entry / OWNERSHIP_MARKER)

    def _is_workspace(self, entry: Path) -> bool:
        return (
            bool(_NAME.fullmatch(entry.name))
            and is_plain_directory(entry)
            and self._is_marked(entry)
        )

    def remove_orphans(self, live_jobs: Collection[uuid.UUID]) -> WorkspaceCleanup:
        """Remove every workspace whose job is not in `live_jobs`.

        Precondition, like `recover_artifacts`: `live_jobs` is read once, so this runs at startup,
        before any worker allocates or uses a workspace (durable liveness is startup recovery's,
        TST-030). Tolerant: one workspace that cannot be removed is reported in `failed` and does
        not stop the rest.
        """
        report = WorkspaceCleanup()
        if not self.root.is_dir():
            return report
        live = set(live_jobs)
        for entry in sorted(self.root.iterdir()):
            if not self._is_workspace(entry):
                report.unowned.append(entry.name)
                continue
            job_id = uuid.UUID(hex=entry.name)
            if job_id in live:
                report.kept.append(job_id)
                continue
            try:
                shutil.rmtree(entry, onexc=_clear_read_only_and_retry)
            except OSError as error:
                report.failed.append((job_id, f"{type(error).__name__}: {error}"))
                continue
            report.removed.append(job_id)
        return report
