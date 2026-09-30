"""Storage usage: what the library holds, what a Recycle Bin purge would free, and what is left.

processing-architecture-v1.md §11: "Storage Manager monitors free disk space and managed-storage
usage... The user may free space, manage the Recycle Bin, remove media". This module only
*reports*. Pausing storage-producing work under disk pressure is the scheduler's decision (M6), and
freeing space is `storage_cleanup` and permanent deletion.

Sizes come from the `artifacts` rows (recorded when each artifact became AVAILABLE), so a report is
one query, not a walk of the library; only the machine-local workspaces are measured on disk, since
no row describes them. Referenced originals are reported separately: they are the user's files, not
space this application occupies or may free.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from backend.app.sources.models import Artifact, ArtifactState, Source, SourceState, StorageMode
from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import WorkspaceManager, is_plain_directory


@dataclass(frozen=True)
class KindUsage:
    kind: str
    artifacts: int
    bytes: int


@dataclass(frozen=True)
class StorageUsage:
    managed: list[KindUsage]  # AVAILABLE managed artifacts, by kind
    managed_bytes: int
    recycled_bytes: int  # the part of `managed_bytes` held by Sources in the Recycle Bin
    referenced_artifacts: int  # external originals: the user's, not ours to free
    referenced_bytes: int
    workspace_bytes: int  # machine-local scratch space, reclaimable by cleanup
    volume_total_bytes: int  # the volume the library lives on
    volume_free_bytes: int


def directory_bytes(path: Path) -> int:
    """Total size of the regular files under `path`. A link, junction or other reparse point is not
    entered (`os.walk` would still descend into a Windows junction), so the total never counts
    bytes the directory merely points at."""
    total = 0
    with os.scandir(path) as entries:
        for entry in entries:
            entry_path = Path(entry.path)
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif is_plain_directory(entry_path):
                total += directory_bytes(entry_path)
    return total


def storage_usage(
    session: Session, roots: StorageRoots, workspaces: WorkspaceManager
) -> StorageUsage:
    rows = session.execute(
        select(Artifact.kind, func.count(), func.coalesce(func.sum(Artifact.size_bytes), 0))
        .where(
            Artifact.storage_mode == StorageMode.MANAGED,
            Artifact.state == ArtifactState.AVAILABLE,
        )
        .group_by(Artifact.kind)
        .order_by(Artifact.kind)
    ).all()
    managed = [KindUsage(kind, count, int(size)) for kind, count, size in rows]

    # Matched with IN, so an artifact is counted once however many Sources in the bin reference it.
    in_the_bin = union_all(
        select(Source.original_artifact_id.label("artifact_id")).where(
            Source.state == SourceState.RECYCLED
        ),
        select(Source.thumbnail_artifact_id).where(
            Source.state == SourceState.RECYCLED, Source.thumbnail_artifact_id.is_not(None)
        ),
    ).subquery()
    recycled_bytes = session.scalar(
        select(func.coalesce(func.sum(Artifact.size_bytes), 0)).where(
            Artifact.id.in_(select(in_the_bin.c.artifact_id)),
            Artifact.storage_mode == StorageMode.MANAGED,
            Artifact.state == ArtifactState.AVAILABLE,
        )
    )

    referenced_count, referenced_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(Artifact.size_bytes), 0)).where(
            Artifact.storage_mode == StorageMode.REFERENCED,
            Artifact.state == ArtifactState.AVAILABLE,
        )
    ).one()

    volume = shutil.disk_usage(roots.library_root)
    return StorageUsage(
        managed=managed,
        managed_bytes=sum(entry.bytes for entry in managed),
        recycled_bytes=int(recycled_bytes or 0),
        referenced_artifacts=referenced_count,
        referenced_bytes=int(referenced_bytes),
        workspace_bytes=directory_bytes(workspaces.root) if workspaces.root.is_dir() else 0,
        volume_total_bytes=volume.total,
        volume_free_bytes=volume.free,
    )
