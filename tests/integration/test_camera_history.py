"""Deleting camera history for good (M7 step 5; plan C9; product spec 9; SEC-006 camera half).

A camera session on the real pipeline (painted squares, scripted frames) records the red person's
encounter and an unknown green face; then one encounter, a time range, or everything is deleted.
Deleted means gone: the encounters and faces leave every read, the vectors are erased (rows, index,
log), the crop files no longer exist on disk, and Evidence stays without them. The people the user
knows stay.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.cameras.history import (
    CameraBusyError,
    CameraNotFoundError,
    DeleteCameraHistory,
    HistorySelection,
)
from backend.app.cameras.session import running_session
from backend.app.identities.models import Evidence, EvidenceRepresentation, Identity
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Occurrence,
    Representation,
)
from backend.app.sources.models import Artifact
from tests.fixtures.camera_pipeline import Camera, empty, picture, visit
from tests.fixtures.pipeline import Pipeline
from tests.integration.test_video_occurrences import enrol_red

EPOCH_MS = 1_793_000_000_000


def wall_clock() -> Any:
    ticks = iter(range(10_000))
    return lambda: (
        datetime.fromtimestamp(EPOCH_MS / 1000, UTC) + timedelta(milliseconds=200 * next(ticks))
    )


@pytest.fixture
def recorded(pipeline: Pipeline) -> tuple[Camera, uuid.UUID]:
    """A camera whose session saw red (known) for a second, then green (unknown) later."""
    red = enrol_red(pipeline)
    camera = Camera(pipeline)
    camera.run(
        *visit("red", 0, 1), *empty(1, 1.6), *visit("green", 2.6, 1), *empty(3.6, 1.6),
        utc_ms=wall_clock(),
    )  # fmt: skip
    return camera, red


def deleter(pipeline: Pipeline, *, running: bool = False) -> DeleteCameraHistory:
    lib = pipeline.lib
    return DeleteCameraHistory(
        lib.unit_of_work, lib.eraser, lib.store, clock=pipeline.clock,
        is_running=(lambda _s, _c: True) if running else
        (lambda session, camera: running_session(session) == camera),
    )  # fmt: skip


def rows(pipeline: Pipeline, model: Any, *where: Any) -> list[Any]:
    with pipeline.lib.session_factory() as session:
        return list(session.scalars(select(model).where(*where)).all())


def seen(face: Observation) -> int:
    assert face.timestamp_ms is not None  # (a camera face always has its moment)
    return face.timestamp_ms


def faces(pipeline: Pipeline, camera: Camera) -> list[Observation]:
    return rows(pipeline, Observation, Observation.source_id == camera.id)


def test_deleting_one_encounter_removes_it_and_its_faces_for_good(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID]
) -> None:
    camera, red = recorded
    (encounter,) = rows(pipeline, Occurrence, Occurrence.source_id == camera.id)
    members = [f for f in faces(pipeline, camera) if seen(f) < EPOCH_MS + 2000]
    crops = rows(pipeline, Artifact, Artifact.id.in_([f.face_crop_artifact_id for f in members]))
    vectors = [r.id for r in rows(pipeline, Representation, Representation.observation_id.in_(
        [f.id for f in members]))]  # fmt: skip
    assert crops
    keys = [crop.storage_key for crop in crops]
    evidence_before = len(rows(pipeline, Evidence))

    report = deleter(pipeline).delete(camera.id, HistorySelection((encounter.id,)))

    assert (report.encounters, report.faces, report.complete) == (1, len(members), True)
    assert rows(pipeline, Occurrence, Occurrence.source_id == camera.id) == []
    left = faces(pipeline, camera)
    assert {f.id for f in left}.isdisjoint({f.id for f in members})
    assert left  # the green face was not chosen and stays
    assert rows(pipeline, Representation, Representation.id.in_(vectors)) == []
    assert rows(pipeline, IndexOperation, IndexOperation.representation_id.in_(vectors)) == []
    assert rows(pipeline, EvidenceRepresentation, EvidenceRepresentation.representation_id.in_(
        vectors)) == []  # fmt: skip
    assert len(rows(pipeline, Evidence)) == evidence_before  # the audit trail stays, detached
    for key in keys:  # the bytes are gone from the disk
        assert key is not None
        assert pipeline.lib.store.digest(key) is None
        assert not pipeline.lib.store.roots.path_for(key).exists()
    assert {i.id for i in rows(pipeline, Identity)} == {red}  # the person stays


def test_deleting_a_time_range_takes_the_faces_seen_in_it(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID]
) -> None:
    camera, _red = recorded
    green = [f for f in faces(pipeline, camera) if seen(f) >= EPOCH_MS + 2000]
    low = min(seen(f) for f in green)

    report = deleter(pipeline).delete(camera.id, HistorySelection(start_ms=low))

    assert (report.faces, report.encounters) == (len(green), 0)  # an unplaced face has none
    assert len(rows(pipeline, Occurrence, Occurrence.source_id == camera.id)) == 1
    assert all(seen(f) < low for f in faces(pipeline, camera))
    report = deleter(pipeline).delete(camera.id, HistorySelection(end_ms=low - 1))
    assert report.encounters == 1
    assert faces(pipeline, camera) == []


def test_deleting_everything_leaves_the_camera_configured(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID]
) -> None:
    camera, red = recorded

    report = deleter(pipeline).delete(camera.id, HistorySelection())

    assert report.complete
    assert faces(pipeline, camera) == []
    assert rows(pipeline, Occurrence, Occurrence.source_id == camera.id) == []
    camera.run(*visit("red", 0, 1), *empty(1, 1.6))  # the camera still records
    assert [
        o.identity_id for o in rows(pipeline, Occurrence, Occurrence.source_id == camera.id)
    ] == [red]


def test_a_crop_that_cannot_be_removed_yet_is_carried_on_by_a_repeat(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    camera, _red = recorded
    store = pipeline.lib.store
    real = store.delete

    def locked(key: str) -> None:
        raise PermissionError("the file is open in another program")

    monkeypatch.setattr(store, "delete", locked)
    first = deleter(pipeline).delete(camera.id, HistorySelection())
    assert not first.complete
    assert first.outstanding
    assert faces(pipeline, camera)  # nothing finalized while bytes are owed

    monkeypatch.setattr(store, "delete", real)
    again = deleter(pipeline).delete(camera.id, HistorySelection())
    assert again.complete
    assert again.faces == 0  # nothing new chosen: the earlier deletion was carried on
    assert faces(pipeline, camera) == []


def test_nothing_is_deleted_while_a_session_runs(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID]
) -> None:
    camera, _red = recorded
    before = len(faces(pipeline, camera))

    with pytest.raises(CameraBusyError) as busy:
        deleter(pipeline, running=True).delete(camera.id, HistorySelection())

    assert busy.value.code == "CAMERA_BUSY"
    assert len(faces(pipeline, camera)) == before


def test_only_a_camera_s_history_can_be_deleted(pipeline: Pipeline) -> None:
    image = pipeline.import_image()
    for not_a_camera in (image, uuid.uuid4()):
        with pytest.raises(CameraNotFoundError) as missing:
            deleter(pipeline).delete(not_a_camera, HistorySelection())
        assert missing.value.code == "CAMERA_NOT_FOUND"


def test_a_two_person_frame_keeps_the_other_encounter(pipeline: Pipeline) -> None:
    enrol_red(pipeline)
    camera = Camera(pipeline)
    both = [(n / 5, picture(("red", 10, 40), ("green", 110, 40))) for n in range(5)]
    camera.run(*both, *empty(1, 1.6))
    (encounter,) = rows(pipeline, Occurrence, Occurrence.source_id == camera.id)

    report = deleter(pipeline).delete(camera.id, HistorySelection((encounter.id,)))

    assert report.encounters == 1
    assert faces(pipeline, camera)  # the green faces of the same frames stay


def test_deleting_an_empty_history_changes_nothing(
    pipeline: Pipeline, recorded: tuple[Camera, uuid.UUID]
) -> None:
    camera, _red = recorded
    deleter(pipeline).delete(camera.id, HistorySelection())

    again = deleter(pipeline).delete(camera.id, HistorySelection())

    assert (again.faces, again.encounters, again.complete) == (0, 0, True)
