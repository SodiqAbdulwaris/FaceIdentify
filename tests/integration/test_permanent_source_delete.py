"""Permanent deletion of a Source on a real library: SQLite, USearch, managed files and restarts
(M5 step 4b; TST-059; identity-and-memory-model-v1.md §40-§45, §54, §57; CONTEXT question 29).

Only perception is planted. The story, with unit-length 4-d vectors: image 1 shows face A (identity
I1), image 2 a face near A (matches I1), image 3 a different face C (identity I2). Deleting an
image removes its bytes, faces, vectors and runs for good; the Evidence it produced stays, keeping
ids and scores but nothing that can be searched, shown or recognised again.
"""

import io
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceRepresentation,
    Identity,
)
from backend.app.jobs.models import Job
from backend.app.lifecycle import open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import IndexOperation, Observation, Occurrence, Representation
from backend.app.people.models import Person
from backend.app.people.use_cases import name_identity
from backend.app.processing.models import (
    ExecutionSegment,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)
from backend.app.settings.app_state import WAL_TRUNCATION_OWED, AppStateRepository
from backend.app.sources.artifact_storage import (
    ArtifactStateError,
    complete_artifact_deletion,
    storage_key_for,
)
from backend.app.sources.lifecycle import SourceBusyError, recycle_source
from backend.app.sources.models import Artifact, ArtifactKind, Source
from backend.app.sources.permanent_delete import (
    DELETED_DISPLAY_NAME,
    PermanentSourceDeletion,
    SourceMissingError,
    SourceNotRecycledError,
)
from backend.infrastructure.db.engine import truncate_wal
from backend.infrastructure.db.unit_of_work import TransactionRetry
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.pipeline import Pipeline, prepare_catalog, unit

A = unit(1, 0, 0, 0)
B = unit(0.95, 0.1, 0, 0)  # near A
C = unit(0, 1, 0, 0)  # unlike A and B


class SimulatedCrash(BaseException):
    """The process dying: no `except Exception` handler gets to tidy up after it."""


@pytest.fixture
def opened(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Any:
    (tmp_path / "library").mkdir()
    state: dict[str, Any] = {}

    @contextmanager
    def opening() -> Iterator[Pipeline]:
        with open_library(
            library_root=tmp_path / "library",
            local_state_root=tmp_path / "local",
            clock=clock,
            new_id=new_id,
            index_batch=50,
            max_index_passes=5,
            transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
            retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
        ) as lib:
            if not state:
                state["catalog"] = prepare_catalog(lib, clock, new_id)
            yield Pipeline(lib, clock, new_id, state["catalog"])

    return opening


def process(lib: Pipeline, vector: np.ndarray) -> tuple[uuid.UUID, uuid.UUID]:
    """One image through the pipeline to an accepted, indexed result: (source id, run id)."""
    lib.perception.vector = vector
    source_id = lib.import_image()
    run_id = lib.execute(source_id)
    lib.accept(run_id, apply_index=True)
    return source_id, run_id


def add_face_crop(lib: Pipeline, source_id: uuid.UUID) -> uuid.UUID:
    """Give the Source's observation a managed face-crop file, as a crop writer would."""
    with Session(lib.lib.engine) as session:
        observation = session.scalars(
            select(Observation).where(Observation.source_id == source_id)
        ).one()
        build = ModelFactory(session, lib.clock, lib.new_id)  # type: ignore[arg-type]
        artifact = build.artifact(kind=ArtifactKind.FACE_CROP)
        artifact.storage_key = storage_key_for(ArtifactKind.FACE_CROP, artifact.id)
        lib.lib.store.store(artifact.storage_key, io.BytesIO(b"a face crop"))
        observation.face_crop_artifact_id = artifact.id
        session.commit()
        return artifact.id


def add_thumbnail(lib: Pipeline, source_id: uuid.UUID) -> uuid.UUID:
    with Session(lib.lib.engine) as session:
        build = ModelFactory(session, lib.clock, lib.new_id)  # type: ignore[arg-type]
        artifact = build.artifact(kind=ArtifactKind.THUMBNAIL)
        artifact.storage_key = storage_key_for(ArtifactKind.THUMBNAIL, artifact.id)
        lib.lib.store.store(artifact.storage_key, io.BytesIO(b"a thumbnail"))
        session.execute(
            update(Source).where(Source.id == source_id).values(thumbnail_artifact_id=artifact.id)
        )
        session.commit()
        return artifact.id


def recycle(lib: Pipeline, source_id: uuid.UUID) -> None:
    def work(session: Session) -> None:
        source = session.get(Source, source_id)
        assert source is not None
        recycle_source(session, source_id, expected_revision=source.revision, clock=lib.clock)

    lib.lib.unit_of_work.write(work)


def owed_marker(lib: Pipeline) -> str | None:
    with lib.lib.session_factory() as session:
        return AppStateRepository(session).get(WAL_TRUNCATION_OWED)


def deletion(lib: Pipeline) -> PermanentSourceDeletion:
    return PermanentSourceDeletion(
        lib.lib.session_factory, lib.lib.unit_of_work, lib.lib.eraser, lib.lib.store,
        clock=lib.clock,
    )  # fmt: skip


def only(lib: Pipeline, query: Any) -> list[Any]:
    with lib.lib.session_factory() as session:
        return list(session.scalars(query))


def owned_by(lib: Pipeline, source_id: uuid.UUID) -> dict[str, int]:
    """How many rows of each Source-owned table the Source has."""
    with lib.lib.session_factory() as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.source_id == source_id)
            )
            or 0
            for model in (Observation, Occurrence, ProcessingRun)
        }


def files_containing(lib: Pipeline, vector: np.ndarray) -> list[str]:
    """The database file, its log and every index file whose bytes contain the vector."""
    needle = vector.tobytes()
    database = Path(str(lib.lib.engine.url.database))
    files = [database, database.with_name(database.name + "-wal")]
    files += [p for p in lib.lib.roots.local_state_root.rglob("*") if p.is_file()]
    return sorted({p.name for p in files if p.exists() and needle in p.read_bytes()})


# --- what may be deleted -----------------------------------------------------------------------


def test_only_a_recycled_source_can_be_deleted(opened: Any) -> None:
    with opened() as lib:
        source_id, _run = process(lib, A)

        with pytest.raises(SourceNotRecycledError):
            deletion(lib).delete(source_id)  # still in the library
        with pytest.raises(SourceMissingError):
            deletion(lib).delete(uuid.uuid4())

        [source] = only(lib, select(Source))
        assert source.state == "ACTIVE"
        assert owned_by(lib, source_id) == {
            "observations": 1,
            "occurrences": 1,
            "processing_runs": 1,
        }


def test_a_source_being_processed_is_not_deleted(opened: Any) -> None:
    with opened() as lib:
        source_id = lib.import_image()
        lib.enqueue(source_id)  # a run is PENDING
        with Session(lib.lib.engine) as session:  # (recycling itself would have refused)
            session.execute(update(Source).values(state="RECYCLED"))
            session.commit()

        with pytest.raises(SourceBusyError):
            deletion(lib).delete(source_id)

        assert only(lib, select(Source.state)) == ["RECYCLED"]


# --- what deletion removes ---------------------------------------------------------------------


def test_deleting_a_source_removes_its_bytes_faces_vectors_and_runs(opened: Any) -> None:
    with opened() as lib:
        keep, _ = process(lib, A)
        gone, gone_run = process(lib, C)
        crop = add_face_crop(lib, gone)
        thumbnail = add_thumbnail(lib, gone)
        kept_before = owned_by(lib, keep)
        [original_id] = only(lib, select(Source.original_artifact_id).where(Source.id == gone))
        [original_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == original_id))
        [crop_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == crop))
        [thumbnail_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == thumbnail))
        space = lib.space_id
        assert files_containing(lib, C)  # the vector is in the index and the database
        [snapshot] = only(
            lib, select(ProcessingRun.configuration_snapshot_id).where(ProcessingRun.id == gone_run)
        )
        recycle(lib, gone)

        report = deletion(lib).delete(gone)

        assert report.complete
        assert report.outstanding == []
        # the bytes: nothing of the image or its crop is left on disk
        assert lib.lib.store.digest(original_key) is None
        assert lib.lib.store.digest(crop_key) is None
        assert lib.lib.store.digest(thumbnail_key) is None
        assert {a.id: a.state for a in only(lib, select(Artifact))}[original_id] == "DELETED"
        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "DELETED"
        # the faces, vectors and runs
        assert owned_by(lib, gone) == {"observations": 0, "occurrences": 0, "processing_runs": 0}
        assert only(lib, select(Job).where(Job.processing_run_id == gone_run)) == []
        assert (
            only(
                lib, select(ExecutionSegment).where(ExecutionSegment.processing_run_id == gone_run)
            )
            == []
        )
        assert (
            only(
                lib,
                select(ProcessingConfigurationSnapshot).where(
                    ProcessingConfigurationSnapshot.id == snapshot
                ),
            )
            == []
        )
        assert len(only(lib, select(Representation))) == 1  # the other image's face
        assert len(lib.global_index(space)) == 1
        assert files_containing(lib, C) == []  # not in the database, the log or any index file
        assert files_containing(lib, A)  # the other image's vector is untouched
        # the Source remains only as a tombstone
        [tombstone] = only(lib, select(Source).where(Source.id == gone))
        assert tombstone.state == "DELETED"
        assert tombstone.display_name == DELETED_DISPLAY_NAME
        assert (tombstone.width, tombstone.height, tombstone.thumbnail_artifact_id) == (
            None,
            None,
            None,
        )
        # the other image is exactly as it was
        assert owned_by(lib, keep) == kept_before
        assert only(lib, select(Source.state).where(Source.id == keep)) == ["ACTIVE"]


def test_a_repeat_changes_nothing(opened: Any) -> None:
    with opened() as lib:
        gone, _ = process(lib, A)
        recycle(lib, gone)
        deletion(lib).delete(gone)
        [first] = only(lib, select(Source).where(Source.id == gone))
        revision = first.revision

        again = deletion(lib).delete(gone)

        assert again.complete
        assert only(lib, select(Source.revision).where(Source.id == gone)) == [revision]


@pytest.mark.parametrize("state", ["AVAILABLE", "MISSING"])  # (the file may have been moved)
def test_a_referenced_original_is_never_touched(opened: Any, tmp_path: Path, state: str) -> None:
    mine = tmp_path / "my-photo.png"
    mine.write_bytes(b"the user's own file")
    with opened() as lib:
        source_id, _ = process(lib, A)
        with Session(lib.lib.engine) as session:
            [original_id] = session.scalars(
                select(Source.original_artifact_id).where(Source.id == source_id)
            )
            session.query(Artifact).filter(Artifact.id == original_id).update(
                {
                    "storage_mode": "REFERENCED",
                    "storage_key": None,
                    "external_path": str(mine),
                    "state": state,
                }
            )
            session.commit()
        recycle(lib, source_id)

        assert deletion(lib).delete(source_id).complete

        assert mine.read_bytes() == b"the user's own file"
        assert {a.id: a.state for a in only(lib, select(Artifact))}[original_id] == "DELETED"


# --- identities, people and Evidence -----------------------------------------------------------


def test_an_unnamed_identity_left_with_nothing_is_deleted_and_a_shared_one_is_not(
    opened: Any,
) -> None:
    with opened() as lib:
        first, _ = process(lib, A)
        second, _ = process(lib, B)  # matches the identity of the first
        third, _ = process(lib, C)  # its own identity
        [shared] = {
            o.identity_id
            for o in only(lib, select(Occurrence).where(Occurrence.source_id.in_([first, second])))
        }
        [alone] = {
            o.identity_id
            for o in only(lib, select(Occurrence).where(Occurrence.source_id == third))
        }
        for source_id in (first, third):
            recycle(lib, source_id)
            deletion(lib).delete(source_id)

        states = {i.id: i.state for i in only(lib, select(Identity))}

        assert states[shared] == "ACTIVE"  # the second image still shows this person
        assert states[alone] == "DELETED"  # nothing of this one is left


def test_a_named_person_survives_the_deletion_of_their_last_image(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        [identity_id] = only(lib, select(Identity.id))
        lib.lib.unit_of_work.write(
            lambda session: name_identity(
                session, identity_id, "Ada", new_id=lib.new_id, clock=lib.clock
            )
        )
        recycle(lib, source_id)

        assert deletion(lib).delete(source_id).complete

        [identity] = only(lib, select(Identity))
        [person] = only(lib, select(Person))
        assert identity.state == "ACTIVE"  # they keep their name; recognition is just unavailable
        assert person.display_name == "Ada"
        assert only(lib, select(Occurrence)) == []
        assert only(lib, select(Representation)) == []


def test_retained_evidence_keeps_its_provenance_but_exposes_no_biometric_material(
    opened: Any,
) -> None:
    with opened() as lib:
        first, first_run = process(lib, A)
        second, _ = process(lib, B)  # its evidence ranks the first image's face as a candidate
        [first_representation] = only(
            lib, select(Representation.id).where(Representation.processing_run_id == first_run)
        )
        before = {e.id: e for e in only(lib, select(Evidence))}
        assert len(before) == 2
        assert any(
            c.representation_id == first_representation
            for c in only(lib, select(EvidenceCandidate))
        )
        recycle(lib, first)
        deletion(lib).delete(first)

        after = {e.id: e for e in only(lib, select(Evidence))}
        links = only(lib, select(EvidenceRepresentation))
        candidates = only(lib, select(EvidenceCandidate))

        # Nothing of the history is lost: every decision, its kind, source, scores and ids stay.
        assert set(after) == set(before)
        for evidence_id, evidence in after.items():
            assert (evidence.kind, evidence.source_id) == (
                before[evidence_id].kind,
                before[evidence_id].source_id,
            )
            assert evidence.payload_json == before[evidence_id].payload_json
        assert candidates  # the second image's decision still lists who it was compared with
        assert all(c.raw_similarity is not None for c in candidates)
        # ... but nothing points at a deleted face any more, and the run it came from is gone.
        assert first_representation not in {link.representation_id for link in links}
        assert first_representation not in {c.representation_id for c in candidates}
        assert [e.processing_run_id for e in after.values() if e.source_id == first] == [None]
        assert (
            only(lib, select(Representation).where(Representation.id == first_representation)) == []
        )
        assert (
            only(
                lib,
                select(IndexOperation).where(
                    IndexOperation.representation_id == first_representation
                ),
            )
            == []
        )
        # No vector is left anywhere: not in a row, not in the log, not in an index file.
        assert files_containing(lib, A) == []
        assert [e.source_id for e in only(lib, select(Evidence))].count(first) == 1
        # The tombstone still resolves the Source id the Evidence names.
        assert only(lib, select(Source.state).where(Source.id == first)) == ["DELETED"]


# --- crashes and restarts ----------------------------------------------------------------------


def test_a_deletion_a_crash_interrupted_is_finished_by_the_next_start(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        recycle(lib, source_id)
        [crop_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == crop))
        stopped = deletion(lib)

        def die(_ids: Any) -> Any:
            raise SimulatedCrash

        monkeypatch.setattr(stopped._eraser, "erase", die)  # after the intent and the bytes
        with pytest.raises(SimulatedCrash):
            stopped.delete(source_id)
        monkeypatch.undo()
        assert only(lib, select(Source.state)) == ["DELETING"]
        assert lib.lib.store.digest(crop_key) is None  # step two had already run
        assert len(only(lib, select(Representation))) == 1  # the vector is still there

    with opened() as lib:  # --- the next start
        reports = deletion(lib).resume()

        assert [(r.source_id, r.complete) for r in reports] == [(source_id, True)]
        assert only(lib, select(Source.state)) == ["DELETED"]
        assert only(lib, select(Representation)) == []
        assert files_containing(lib, C) == []
        assert deletion(lib).resume() == []  # nothing left to carry on


def test_a_crash_before_the_finalizing_transaction_leaves_nothing_resurrectable(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)
        stopped = deletion(lib)

        def die(*_args: Any) -> Any:
            raise SimulatedCrash

        monkeypatch.setattr(stopped, "_finalize", die)
        with pytest.raises(SimulatedCrash):
            stopped.delete(source_id)  # bytes gone, vectors erased, rows not yet deleted
        monkeypatch.undo()

        # What survives cannot bring the face back: the vector is cleared and the Source is
        # DELETING, so it is neither shown, processed, restored nor recognised.
        assert [r.state for r in only(lib, select(Representation))] == ["ERASED"]
        assert files_containing(lib, C) == []
        with pytest.raises(Exception, match="DELETING"):
            recycle(lib, source_id)

    with opened() as lib:
        assert [r.complete for r in deletion(lib).resume()] == [True]
        assert only(lib, select(Observation)) == []


def test_bytes_that_cannot_be_removed_are_reported_and_retried(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)

        def locked(_key: str) -> None:
            raise PermissionError("in use")

        monkeypatch.setattr(lib.lib.store, "delete", locked)
        report = deletion(lib).delete(source_id)

        assert not report.complete
        assert "PermissionError" in report.outstanding[0]
        assert only(lib, select(Source.state)) == ["DELETING"]
        assert only(lib, select(Artifact.state).where(Artifact.state == "DELETE_FAILED"))
        monkeypatch.undo()

        retried = deletion(lib).resume()

        assert [r.complete for r in retried] == [True]
        assert only(lib, select(Source.state)) == ["DELETED"]


def test_finalization_refuses_while_a_face_vector_is_left(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)
        stopped = deletion(lib)
        lib.lib.unit_of_work.write(lambda session: stopped._begin(session, source_id, lib.clock()))

        with pytest.raises(Exception, match="face vector"):
            lib.lib.unit_of_work.write(
                lambda session: stopped._finalize(session, source_id, lib.clock())
            )

        assert len(only(lib, select(Observation))) == 1  # the refusal rolled everything back


# --- edges -------------------------------------------------------------------------------------


def test_artifacts_already_deleted_or_being_deleted_are_not_started_again(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        recycle(lib, source_id)
        with Session(lib.lib.engine) as session:  # the original was already taken by a cleanup
            session.execute(
                update(Artifact)
                .where(Artifact.id == crop)
                .values(state="DELETING", delete_requested_at=lib.clock())
            )
            [original] = session.scalars(select(Source.original_artifact_id))
            session.execute(
                update(Artifact)
                .where(Artifact.id == original)
                .values(state="DELETED", deleted_at=lib.clock())
            )
            session.commit()

        report = deletion(lib).delete(source_id)

        assert report.complete
        ours = only(lib, select(Artifact).where(Artifact.id.in_([crop, original])))
        assert {a.state for a in ours} == {"DELETED"}


def test_one_failing_source_does_not_stop_startup_from_carrying_on_the_rest(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)
        lib.lib.unit_of_work.write(
            lambda session: deletion(lib)._begin(session, source_id, lib.clock())
        )
        stuck = deletion(lib)

        def broken(_source_id: uuid.UUID) -> Any:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(stuck, "_carry_on", broken)
        [report] = stuck.resume()

        assert (report.source_id, report.complete) == (source_id, False)
        assert report.outstanding == ["RuntimeError: disk on fire"]
        assert only(lib, select(Source.state)) == ["DELETING"]  # left for the next start


def test_steps_refuse_a_source_that_is_not_where_they_expect(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)
        steps = deletion(lib)

        with pytest.raises(SourceMissingError):
            steps._carry_on(uuid.uuid4())
        with pytest.raises(SourceNotRecycledError):
            steps._carry_on(source_id)  # still RECYCLED: no intent was recorded
        with pytest.raises(SourceMissingError):
            lib.lib.unit_of_work.write(lambda s: steps._finalize(s, uuid.uuid4(), lib.clock()))
        with pytest.raises(Exception, match="not DELETING"):
            lib.lib.unit_of_work.write(lambda s: steps._finalize(s, source_id, lib.clock()))
        assert len(only(lib, select(Observation))) == 1


def test_bytes_are_only_removed_for_an_artifact_whose_deletion_was_recorded(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        [original] = only(lib, select(Source.original_artifact_id).where(Source.id == source_id))
        [key] = only(lib, select(Artifact.storage_key).where(Artifact.id == original))

        with pytest.raises(ArtifactStateError):
            complete_artifact_deletion(
                lib.lib.session_factory, lib.lib.store, original, clock=lib.clock
            )  # AVAILABLE: nobody asked for it to go
        with pytest.raises(ArtifactStateError):
            complete_artifact_deletion(
                lib.lib.session_factory, lib.lib.store, uuid.uuid4(), clock=lib.clock
            )

        assert lib.lib.store.digest(key) is not None


# --- what the review of PR 156 found ------------------------------------------------------------


def test_the_landmarks_and_quality_data_of_deleted_faces_are_not_left_in_the_database_files(
    opened: Any,
) -> None:
    marker = "LANDMARKS-OF-A-DELETED-FACE-0123456789"
    with opened() as lib:
        source_id, _ = process(lib, C)
        with Session(lib.lib.engine) as session:
            session.execute(
                update(Observation).values(
                    landmarks_json={"eye": marker}, quality_json={"note": marker + "-quality"}
                )
            )
            session.commit()
        database = Path(str(lib.lib.engine.url.database))
        assert (
            marker.encode()
            in database.read_bytes() + database.with_name(database.name + "-wal").read_bytes()
        )
        recycle(lib, source_id)

        report = deletion(lib).delete(source_id)

        assert report.complete
        leftovers = [
            path.name
            for path in (database, database.with_name(database.name + "-wal"))
            if path.exists() and marker.encode() in path.read_bytes()
        ]
        assert leftovers == []


def test_a_log_that_cannot_be_truncated_keeps_the_deletion_unfinished_until_it_is(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    truncating = "backend.app.memory.erasure.truncate_wal"
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)
        monkeypatch.setattr(truncating, lambda *_a, **_k: False)

        blocked = deletion(lib).delete(source_id)  # the vectors' own cleanup cannot finish

        assert not blocked.complete
        assert only(lib, select(Source.state)) == ["DELETING"]
        # Now only the log of the rows' deletion is owed: the first call (the vectors') succeeds.
        calls: list[int] = []

        def once(engine: Any, **kwargs: Any) -> bool:
            calls.append(1)
            return len(calls) == 1 and truncate_wal(engine, **kwargs)

        monkeypatch.setattr(truncating, once)

        owed = deletion(lib).delete(source_id)

        assert not owed.complete
        assert any("write-ahead log" in item for item in owed.outstanding)
        assert only(lib, select(Source.state)) == ["DELETED"]  # the rows are gone; the log is owed

        assert owed_marker(lib) is not None
        monkeypatch.undo()

        again = deletion(lib).delete(source_id)  # a repeat settles the log

        assert again.complete
        assert not again.changed
        assert owed_marker(lib) is None


def test_a_write_that_never_finished_is_removed_too(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        [crop_key] = only(lib, select(Artifact.storage_key).where(Artifact.id == crop))
        staged = lib.lib.store.staging_path(crop_key)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(b"half a crop")
        with Session(lib.lib.engine) as session:
            session.execute(update(Artifact).where(Artifact.id == crop).values(state="PENDING"))
            session.commit()
        recycle(lib, source_id)

        report = deletion(lib).delete(source_id)

        assert report.complete
        assert lib.lib.store.digest(crop_key) is None
        assert not staged.exists()
        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "DELETED"


def test_an_artifact_nobody_is_deleting_blocks_completion(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        recycle(lib, source_id)
        steps = deletion(lib)
        lib.lib.unit_of_work.write(lambda s: steps._begin(s, source_id, lib.clock()))
        with Session(lib.lib.engine) as session:  # it fell back to a state no step handles
            session.execute(update(Artifact).where(Artifact.id == crop).values(state="PENDING"))
            session.commit()

        report = steps._carry_on(source_id)

        assert not report.complete
        assert report.outstanding == [f"artifact {crop} is not deleted"]
        assert only(lib, select(Source.state)) == ["DELETING"]
        assert len(only(lib, select(Observation))) == 1


def test_a_representation_marked_deleted_still_loses_its_vector(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        assert files_containing(lib, C)
        with Session(lib.lib.engine) as session:
            session.execute(update(Representation).values(state="DELETED"))
            session.commit()
        recycle(lib, source_id)

        report = deletion(lib).delete(source_id)

        assert report.complete
        assert files_containing(lib, C) == []  # not in the database, the log or any index file


def test_a_source_being_deleted_is_out_of_recognition_and_every_reader_at_once(
    opened: Any,
) -> None:
    with opened() as lib:
        first, _ = process(lib, A)
        recycle(lib, first)
        steps = deletion(lib)
        lib.lib.unit_of_work.write(lambda s: steps._begin(s, first, lib.clock()))  # intent only

        assert {r.state for r in only(lib, select(Representation))} == {"ERASING"}
        assert {o.state for o in only(lib, select(Occurrence))} == {"DELETED"}
        assert {o.state for o in only(lib, select(Observation))} == {"DELETED"}
        second, _ = process(lib, unit(0.99, 0.05, 0, 0))  # a face just like the one being deleted

        kinds = sorted(only(lib, select(Evidence.kind)))
        assert kinds == ["IDENTITY_CREATED", "RECOGNITION_ABSTAINED"]  # not IDENTITY_MATCHED
        assert only(lib, select(Occurrence.identity_id).where(Occurrence.source_id == second)) == []


def test_two_requests_at_once_do_not_trip_over_each_other(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        recycle(lib, source_id)
        slow, fast = deletion(lib), deletion(lib)
        lib.lib.unit_of_work.write(lambda s: slow._begin(s, source_id, lib.clock()))
        assert fast.delete(source_id).complete  # the other request finishes first

        # The slow one wakes up late and finds everything done.
        complete_artifact_deletion(lib.lib.session_factory, lib.lib.store, crop, clock=lib.clock)
        lib.lib.unit_of_work.write(lambda s: slow._finalize(s, source_id, lib.clock()))
        report = slow._carry_on(source_id)

        assert report.complete
        assert only(lib, select(Source.state)) == ["DELETED"]


def test_the_other_request_finishing_an_artifact_midway_is_not_an_error(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        crop = add_face_crop(lib, source_id)
        recycle(lib, source_id)
        steps = deletion(lib)
        lib.lib.unit_of_work.write(lambda s: steps._begin(s, source_id, lib.clock()))
        store = lib.lib.store
        real = store.delete
        raced: list[str] = []

        def racing(key: str) -> None:
            real(key)
            if not raced:  # while this one removes the bytes, the other request finishes the job
                raced.append(key)
                complete_artifact_deletion(lib.lib.session_factory, store, crop, clock=lib.clock)

        monkeypatch.setattr(store, "delete", racing)

        complete_artifact_deletion(lib.lib.session_factory, store, crop, clock=lib.clock)

        assert {a.id: a.state for a in only(lib, select(Artifact))}[crop] == "DELETED"


def test_a_long_history_is_deleted_in_bounded_statements(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import event

    from backend.app.sources import permanent_delete

    with opened() as lib:
        source_id, _ = process(lib, C)
        for _ in range(2):  # two more runs of the same image
            lib.accept(lib.execute(source_id), apply_index=True)
        recycle(lib, source_id)
        monkeypatch.setattr(permanent_delete, "CHUNK", 1)
        statements: list[str] = []
        event.listen(
            lib.lib.engine,
            "before_cursor_execute",
            lambda _c, _cur, statement, *_rest: statements.append(statement),
        )

        assert deletion(lib).delete(source_id).complete

        snapshot_deletes = [s for s in statements if s.startswith("DELETE FROM processing_config")]
        assert len(snapshot_deletes) == 3  # one per run, never one statement for all of them


def test_a_person_still_seen_elsewhere_keeps_a_face_to_show(opened: Any) -> None:
    with opened() as lib:
        first, _ = process(lib, A)
        second, _ = process(lib, B)  # the same identity
        [identity] = only(lib, select(Identity))
        [second_face] = only(lib, select(Observation.id).where(Observation.source_id == second))
        [first_face] = only(lib, select(Observation.id).where(Observation.source_id == first))
        with Session(lib.lib.engine) as session:
            session.execute(update(Identity).values(representative_observation_id=first_face))
            session.commit()
        revision = identity.revision
        recycle(lib, first)

        assert deletion(lib).delete(first).complete

        [after] = only(lib, select(Identity))
        assert after.state == "ACTIVE"
        assert after.representative_observation_id == second_face
        assert after.revision == revision + 1


def test_what_describes_a_deleted_file_goes_with_it(opened: Any) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        [original] = only(lib, select(Source.original_artifact_id))
        with Session(lib.lib.engine) as session:
            session.execute(
                update(Artifact)
                .where(Artifact.id == original)
                .values(original_filename="Ada-holiday.jpg", mime_type="image/jpeg")
            )
            session.commit()
        recycle(lib, source_id)

        assert deletion(lib).delete(source_id).complete

        [artifact] = only(lib, select(Artifact).where(Artifact.id == original))
        assert (artifact.original_filename, artifact.mime_type) == (None, None)
        assert (artifact.sha256, artifact.size_bytes) == (None, None)


def test_a_retry_that_changes_nothing_is_not_reported_as_a_change(
    opened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened() as lib:
        source_id, _ = process(lib, C)
        recycle(lib, source_id)

        def locked(_key: str) -> None:
            raise PermissionError("in use")

        monkeypatch.setattr(lib.lib.store, "delete", locked)
        first = deletion(lib).delete(source_id)
        second = deletion(lib).delete(source_id)
        monkeypatch.undo()
        third = deletion(lib).delete(source_id)

        assert (first.changed, second.changed, third.changed) == (True, False, True)
