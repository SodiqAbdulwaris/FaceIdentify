"""Storage usage: what the library holds, how much of it belongs to the Recycle Bin, what is left.

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
    # The part of `managed_bytes` associated with Sources in the Recycle Bin (their originals and
    # thumbnails, each once). An artifact another row also references is included, so this is an
    # upper bound on what purging the bin frees: which bytes are freed is permanent deletion's
    # rule (TST-031), not something a report can know.
    recycled_bytes: int
    referenced_artifacts: int  # external originals: the user's, not ours to free
    referenced_bytes: int  # only those whose size is known
    referenced_size_unknown: int  # AVAILABLE referenced artifacts with no recorded size
    workspace_bytes: int  # machine-local scratch space, reclaimable by cleanup
    workspace_unreadable: int  # workspace directories that could not be listed, so undercounted
    volume_total_bytes: int  # the volume the library lives on
    volume_free_bytes: int


@dataclass(frozen=True)
class Measured:
    bytes: int
    unreadable: int  # directories that could not be listed; what they hold is not in `bytes`


def measure_directory(path: Path) -> Measured:
    """Total size of the regular files under `path`.

    A link, junction or other reparse point is not entered (`os.walk` would still descend into a
    Windows junction), so the total never counts bytes the directory merely points at. The walk is
    iterative, so depth cannot exhaust the stack. A directory that vanishes mid-walk (a job
    finishing) is simply absent; one that cannot be listed (denied) is counted in `unreadable`
    instead of crashing the report or being silently forgotten. (A file's size comes from the
    listing itself, so a file vanishing mid-walk cannot fail here.)
    """
    total = unreadable = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif is_plain_directory(Path(entry.path)):
                        pending.append(Path(entry.path))
        except FileNotFoundError:
            continue
        except OSError:
            unreadable += 1
    return Measured(total, unreadable)


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

    # count(size_bytes) counts only the known sizes, so the difference is the unknown ones.
    referenced_count, referenced_known, referenced_bytes = session.execute(
        select(
            func.count(), func.count(Artifact.size_bytes),
            func.coalesce(func.sum(Artifact.size_bytes), 0),
        ).where(
            Artifact.storage_mode == StorageMode.REFERENCED,
            Artifact.state == ArtifactState.AVAILABLE,
        )
    ).one()  # fmt: skip

    # Only workspaces this manager made (marked, real directories), not whatever else is there.
    measured = [measure_directory(workspaces.path_for(job)) for job in workspaces.existing()]

    volume = shutil.disk_usage(roots.library_root)
    return StorageUsage(
        managed=managed,
        managed_bytes=sum(entry.bytes for entry in managed),
        recycled_bytes=int(recycled_bytes or 0),
        referenced_artifacts=referenced_count,
        referenced_bytes=int(referenced_bytes),
        referenced_size_unknown=referenced_count - referenced_known,
        workspace_bytes=sum(m.bytes for m in measured),
        workspace_unreadable=sum(m.unreadable for m in measured),
        volume_total_bytes=volume.total,
        volume_free_bytes=volume.free,
    )
