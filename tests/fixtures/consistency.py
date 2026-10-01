"""A cross-storage consistency check: do SQLite, the managed files and the USearch indexes agree?

SQLite is authoritative; the files and the indexes are derived or owned by it
(PERSISTENCE_IMPLEMENTATION.md §1, §23; INDEX-01 and INDEX-02). After any interruption and a startup
recovery, this must find nothing. Each problem is a sentence, so a failing test says what disagrees.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.identities.models import Identity, IdentityState
from backend.app.memory.index_coordinator import USEARCH_METRICS, IndexCoordinator
from backend.app.memory.models import (
    IndexOperation,
    IndexOperationState,
    Representation,
    RepresentationSpace,
    RepresentationSpaceState,
    RepresentationState,
)
from backend.app.sources.artifact_storage import scan_storage, verify_artifact
from backend.app.sources.models import Artifact, ArtifactState, StorageMode
from backend.infrastructure.indexing.representation_index import (
    IndexUnusableError,
    RepresentationIndex,
)
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import UnsafeStorageKeyError


def library_problems(
    factory: sessionmaker[Session],
    store: ManagedFileStore,
    coordinator: IndexCoordinator,
    *,
    now: datetime,
    allow_orphans: bool = False,
) -> list[str]:
    """Every way the three stores disagree. `allow_orphans`: files no row owns are reported by the
    scan and never deleted (the row may only be lost), so after recovery they may legitimately
    remain."""
    problems: list[str] = []
    with factory() as session:
        _artifact_problems(session, store, problems, allow_orphans)
        _index_problems(session, coordinator, now, problems)
    return problems


def _artifact_problems(
    session: Session, store: ManagedFileStore, problems: list[str], allow_orphans: bool
) -> None:
    for artifact in session.scalars(
        select(Artifact).where(Artifact.storage_mode == StorageMode.MANAGED)
    ):
        if artifact.state in {ArtifactState.PENDING, ArtifactState.DELETING}:
            problems.append(f"artifact {artifact.id} is still {artifact.state}")
        if artifact.state == ArtifactState.AVAILABLE:
            try:
                intact = verify_artifact(store, artifact)
            except UnsafeStorageKeyError:
                intact = False
            if not intact:
                problems.append(f"artifact {artifact.id} is AVAILABLE but its bytes are not")
    scan = scan_storage(session, store)
    if scan.stray_staging:
        problems.append(f"staging files remain: {scan.stray_staging}")
    if scan.orphans and not allow_orphans:
        problems.append(f"files no row owns: {scan.orphans}")


def _index_problems(
    session: Session, coordinator: IndexCoordinator, now: datetime, problems: list[str]
) -> None:
    due = session.scalars(
        select(IndexOperation.id).where(
            IndexOperation.state == IndexOperationState.PENDING,
            IndexOperation.not_before_at <= now,
        )
    ).all()
    if due:
        problems.append(f"{len(due)} index operations are pending and due")
    for space in session.scalars(
        select(RepresentationSpace).where(
            RepresentationSpace.state == RepresentationSpaceState.ACTIVE
        )
    ):
        expected = set(
            session.scalars(
                select(Representation.ann_key)
                .join(Identity, Identity.id == Representation.identity_id)
                .where(
                    Representation.representation_space_id == space.id,
                    Representation.state == RepresentationState.ACTIVE,
                    Identity.state == IdentityState.ACTIVE,
                )
            )
        )
        try:
            index = RepresentationIndex.open(
                coordinator.index_directory(space.id),
                representation_space_id=space.id,
                ndim=space.dimension,
                metric=USEARCH_METRICS[space.metric],
            )
        except IndexUnusableError as error:
            if not expected and str(error) == "no manifest":
                continue  # nothing is eligible, so there is nothing an index would hold
            problems.append(f"space {space.id} has no usable index: {error}")
            continue
        missing = sorted(key for key in expected if key is not None and not index.contains(key))
        if missing:
            problems.append(f"space {space.id} index lacks keys {missing}")
        if len(index) != len(expected) - len(missing):
            problems.append(
                f"space {space.id} index holds {len(index)} entries for {len(expected)} eligible"
            )
