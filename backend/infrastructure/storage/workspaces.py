"""Temporary job workspaces under machine-local `temp/jobs/<job id>/`.

IMPLEMENTATION_ARCHITECTURE.md §16.5: subsystems "may manipulate temporary computational files only
within controlled allocated workspaces". A workspace holds disposable, reconstructable files
(decoded frames, crops, intermediates), never authoritative bytes, so it lives in the
machine-local root (tech-stack.md §15), not the library.

The manager owns only directories it names itself: `<32 lower-case hex job id>`. Anything else
under `temp/jobs/` is not its to delete. Deciding *which* jobs are live is the caller's (it needs
the database); PERSISTENCE_IMPLEMENTATION.md §28: "remove only application-owned workspace after
verifying no live run needs it". This module knows nothing about the database.
"""

import re
import shutil
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from backend.infrastructure.storage.layout import StorageRoots

WORKSPACE_SUBDIRECTORIES = ("decode", "frames", "crops", "intermediate")
_NAME = re.compile(r"[0-9a-f]{32}")


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
        resumed job gets its existing workspace back, files included."""
        path = self.path_for(job_id)
        for name in WORKSPACE_SUBDIRECTORIES:
            (path / name).mkdir(parents=True, exist_ok=True)
        return path

    def release(self, job_id: uuid.UUID) -> None:
        """Remove the job's workspace and everything in it. Idempotent. Never follows a link out of
        the workspace, and refuses a workspace that is itself a link."""
        path = self.path_for(job_id)
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"workspace {path.name} is a link, not a directory this manager made")
        if path.exists():
            shutil.rmtree(path)

    def existing(self) -> list[uuid.UUID]:
        """The job ids that currently have a workspace directory."""
        if not self.root.is_dir():
            return []
        return sorted(
            uuid.UUID(hex=entry.name)
            for entry in self.root.iterdir()
            if _NAME.fullmatch(entry.name) and self._is_workspace(entry)
        )

    @staticmethod
    def _is_workspace(entry: Path) -> bool:
        return entry.is_dir() and not (entry.is_symlink() or entry.is_junction())

    def remove_orphans(self, live_jobs: Collection[uuid.UUID]) -> WorkspaceCleanup:
        """Remove every workspace whose job is not in `live_jobs`.

        Tolerant, like startup recovery: one workspace that cannot be removed is reported in
        `failed` and does not stop the rest.
        """
        report = WorkspaceCleanup()
        if not self.root.is_dir():
            return report
        live = set(live_jobs)
        for entry in sorted(self.root.iterdir()):
            if not (_NAME.fullmatch(entry.name) and self._is_workspace(entry)):
                report.unowned.append(entry.name)
                continue
            job_id = uuid.UUID(hex=entry.name)
            if job_id in live:
                report.kept.append(job_id)
                continue
            try:
                shutil.rmtree(entry)
            except OSError as error:
                report.failed.append((job_id, f"{type(error).__name__}: {error}"))
                continue
            report.removed.append(job_id)
        return report
