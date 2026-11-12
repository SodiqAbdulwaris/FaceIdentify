"""Cameras: configure a capture device, run one session at a time, see it, delete its history
(M7 step 5; API and Contracts section 4, decision 2026-11-11; plan section 5, C2 to C9).

A camera is a `CAMERA` Source with its device. Its encounters are read through the existing
occurrence and unresolved-face reads of its Source (`/sources/{id}/occurrences`,
`/sources/{id}/unresolved-faces`); a camera face has no picture to cut it from, so its stored face
crop is served here (`/cameras/{id}/faces/{observation_id}/crop`). The preview is the newest
annotated frame, from memory only. Deleting history is permanent (C9): one encounter, several, a
time range, or all of it; deleting the camera itself can take its whole history with it.
"""

import uuid
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.routes.sources import DeletionPending
from backend.api.startup import Backend, ProcessingUnavailableError
from backend.app.cameras.history import (
    CameraBusyError as HistoryBusyError,
)
from backend.app.cameras.history import (
    CameraNotFoundError as HistoryNotFoundError,
)
from backend.app.cameras.history import (
    DeleteCameraHistory,
    HistorySelection,
)
from backend.app.cameras.models import CameraSourceMetadata
from backend.app.cameras.service import CameraService, CameraStatus
from backend.app.cameras.session import (
    CameraBusyError,
    CameraNotConfiguredError,
    running_session,
)
from backend.app.memory.models import Observation, ObservationState
from backend.app.sources.lifecycle import recycle_source
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceKind, SourceState
from backend.app.sources.permanent_delete import PermanentSourceDeletion
from backend.infrastructure.media.camera import CameraError, CaptureDevice, list_devices
from backend.infrastructure.media.video import MediaToolsMissingError, media_tools

router = APIRouter(tags=["cameras"])

Cameras = Annotated[Backend, Depends(get_backend)]


class CaptureDeviceModel(BaseModel):
    name: str
    path: str | None


class CameraCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    device_name: str = Field(min_length=1, max_length=500)
    device_path: str | None = Field(default=None, min_length=1, max_length=2000)


class CameraSummary(BaseModel):
    id: str
    display_name: str
    device_name: str
    device_path: str | None
    session: "SessionStatus"


class SessionStatus(BaseModel):
    """`state` None: no session since the application started."""

    state: str | None
    job_id: str | None
    frames: int
    dropped: int
    open_encounters: int
    encounters: int
    failure_code: str | None


class HistoryDelete(BaseModel):
    """Which history to delete: these encounters, and every face seen between `start_ms` and
    `end_ms` (UTC milliseconds, inclusive). An empty body deletes all of it."""

    occurrence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class HistoryDeleted(BaseModel):
    faces: int
    encounters: int
    complete: bool


def camera_not_found(camera_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "CAMERA_NOT_FOUND", "The requested camera could not be found.",
        details={"camera_id": str(camera_id)},
    )  # fmt: skip


def camera_busy(camera_id: uuid.UUID) -> ApiError:
    return ApiError(
        409, "CAMERA_BUSY", "A camera session is running; stop it first.",
        details={"camera_id": str(camera_id)},
    )  # fmt: skip


def require_cameras(backend: Cameras) -> CameraService:
    if backend.cameras is None:
        raise ApiError(503, "PROCESSING_UNAVAILABLE", "Processing is not configured.")
    return backend.cameras


Service = Annotated[CameraService, Depends(require_cameras)]


def _status(status: CameraStatus) -> SessionStatus:
    return SessionStatus(
        state=None if status.state is None else status.state.value,
        job_id=None if status.job_id is None else str(status.job_id),
        frames=status.frames,
        dropped=status.dropped,
        open_encounters=status.open_encounters,
        encounters=status.encounters,
        failure_code=status.failure_code,
    )


def _summary(
    service: CameraService,
    camera_id: uuid.UUID,
    display_name: str,
    device_name: str,
    device_path: str | None,
) -> CameraSummary:
    return CameraSummary(
        id=str(camera_id),
        display_name=display_name,
        device_name=device_name,
        device_path=device_path,
        session=_status(service.status(camera_id)),
    )


def _cameras(session: Session, camera_id: uuid.UUID | None = None) -> list[Any]:
    query = (
        select(
            Source.id,
            Source.display_name,
            CameraSourceMetadata.device_name,
            CameraSourceMetadata.device_path,
        )
        .join(CameraSourceMetadata, CameraSourceMetadata.source_id == Source.id)
        .where(Source.kind == SourceKind.CAMERA, Source.state == SourceState.ACTIVE)
        .order_by(Source.created_at, Source.id)
    )
    if camera_id is not None:
        query = query.where(Source.id == camera_id)
    return list(session.execute(query).tuples())


@router.get("/cameras/devices")
async def devices(library: Library) -> list[CaptureDeviceModel]:
    """The capture devices this computer offers now (asked of DirectShow every time)."""
    try:
        tools = media_tools(library.roots.local_state_root)
        found = await anyio.to_thread.run_sync(list_devices, tools)
    except MediaToolsMissingError:
        raise ApiError(
            503, "MEDIA_TOOLS_UNAVAILABLE", "Camera support (FFmpeg) is not installed."
        ) from None
    except CameraError:
        raise ApiError(
            503, "CAMERA_DISCONNECTED", "The capture devices could not be listed."
        ) from None
    return [CaptureDeviceModel(name=d.name, path=d.path) for d in found]


@router.post("/cameras", status_code=201)
def configure(body: CameraCreate, library: Library, service: Service) -> CameraSummary:
    camera_id = service.configure(
        body.display_name.strip(), CaptureDevice(body.device_name, body.device_path)
    )
    (row,) = library.unit_of_work.read(lambda session: _cameras(session, camera_id))
    return _summary(service, *row)


@router.get("/cameras")
def list_cameras(library: Library, service: Service) -> list[CameraSummary]:
    """Every configured camera (a short list: no pagination)."""
    rows = library.unit_of_work.read(_cameras)
    return [_summary(service, *row) for row in rows]


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: uuid.UUID, library: Library, service: Service) -> CameraSummary:
    rows = library.unit_of_work.read(lambda session: _cameras(session, camera_id))
    if not rows:
        raise camera_not_found(camera_id)
    return _summary(service, *rows[0])


def require_camera(library: Any, camera_id: uuid.UUID) -> None:
    """`404 CAMERA_NOT_FOUND` unless the camera is configured (and not removed)."""
    if not library.unit_of_work.read(lambda session: _cameras(session, camera_id)):
        raise camera_not_found(camera_id)


@router.delete("/cameras/{camera_id}", status_code=204, responses={202: {"model": DeletionPending}})
def remove_camera(
    camera_id: uuid.UUID,
    library: Library,
    service: Service,
    backend: Cameras,
    history: Annotated[
        bool, Query(description="Also delete all of its history, for good.")
    ] = False,
) -> Response:
    """Remove the configuration; its history stays unless `history=true` (C9). With the
    history, `202` and what is still owed when part of the deletion cannot finish yet (a locked
    file); it is finished at the next start."""
    if not history:
        try:
            service.remove(camera_id)
        except CameraNotConfiguredError:
            raise camera_not_found(camera_id) from None
        except CameraBusyError:
            raise camera_busy(camera_id) from None
        return Response(status_code=204)

    def recycle(session: Session) -> None:
        service.device(session, camera_id)
        if running_session(session) == camera_id:
            raise CameraBusyError("running")
        source = session.get(Source, camera_id)
        assert source is not None
        recycle_source(
            session, camera_id, expected_revision=source.revision, clock=backend.settings.clock
        )

    try:
        library.unit_of_work.write(recycle)
    except CameraNotConfiguredError:
        raise camera_not_found(camera_id) from None
    except CameraBusyError:
        raise camera_busy(camera_id) from None
    report = PermanentSourceDeletion(
        library.session_factory, library.unit_of_work, library.eraser, library.store,
        clock=backend.settings.clock, new_id=backend.settings.new_id,
    ).delete(camera_id)  # fmt: skip
    if report.complete:
        return Response(status_code=204)
    backend.capabilities["recovery"] = "DEGRADED"  # finished at the next start
    pending = DeletionPending(state=SourceState.DELETING, outstanding=report.outstanding)
    return JSONResponse(pending.model_dump(), status_code=202)


@router.post("/cameras/{camera_id}/start", status_code=202)
def start(camera_id: uuid.UUID, service: Service, library: Library) -> SessionStatus:
    try:
        service.start(camera_id)
    except CameraNotConfiguredError:
        raise camera_not_found(camera_id) from None
    except CameraBusyError:
        raise camera_busy(camera_id) from None
    except ProcessingUnavailableError:
        raise ApiError(
            503, "PROCESSING_UNAVAILABLE", "No processing configuration is available."
        ) from None
    return _status(service.status(camera_id))


@router.post("/cameras/{camera_id}/stop", status_code=202)
async def stop(camera_id: uuid.UUID, service: Service, library: Library) -> SessionStatus:
    """Stop the session; its open encounters are recorded before it ends."""
    require_camera(library, camera_id)
    await anyio.to_thread.run_sync(service.stop, camera_id)
    return _status(service.status(camera_id))


@router.get("/cameras/{camera_id}/status")
def status(camera_id: uuid.UUID, service: Service, library: Library) -> SessionStatus:
    require_camera(library, camera_id)
    return _status(service.status(camera_id))


@router.get(
    "/cameras/{camera_id}/preview",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def preview(camera_id: uuid.UUID, service: Service, library: Library) -> Response:
    """The newest frame with its faces outlined, while a session runs. Never stored."""
    require_camera(library, camera_id)
    picture = service.preview(camera_id)
    if picture is None:
        raise ApiError(404, "MEDIA_NOT_FOUND", "No live picture is available.")
    return Response(picture, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get(
    "/cameras/{camera_id}/faces/{observation_id}/crop",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def face_crop(camera_id: uuid.UUID, observation_id: uuid.UUID, library: Library) -> Response:
    """A camera face as it was kept (its face crop)."""

    def find(session: Session) -> str | None:
        return session.scalar(
            select(Artifact.storage_key)
            .join(Observation, Observation.face_crop_artifact_id == Artifact.id)
            .join(Source, Source.id == Observation.source_id)
            .where(
                Observation.id == observation_id,
                Observation.source_id == camera_id,
                Observation.state == ObservationState.ACTIVE,
                Source.kind == SourceKind.CAMERA,
                Artifact.state == ArtifactState.AVAILABLE,
            )
        )

    key = library.unit_of_work.read(find)
    if key is None:
        raise ApiError(404, "MEDIA_NOT_FOUND", "The face picture could not be found.")
    with library.store.open(key) as stream:
        data = stream.read()
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private"})


@router.post("/cameras/{camera_id}/history/delete")
def delete_history(
    camera_id: uuid.UUID, body: HistoryDelete, library: Library, backend: Cameras
) -> HistoryDeleted:
    """Delete encounters and faces for good (C9): no Recycle bin."""
    if body.start_ms is not None and body.end_ms is not None and body.start_ms > body.end_ms:
        raise ApiError(422, "VALIDATION_ERROR", "start_ms must not be after end_ms.")
    deletion = DeleteCameraHistory(
        library.unit_of_work, library.eraser, library.store,
        clock=backend.settings.clock,
        is_running=lambda session, camera: running_session(session) == camera,
    )  # fmt: skip
    try:
        report = deletion.delete(
            camera_id,
            HistorySelection(tuple(body.occurrence_ids), body.start_ms, body.end_ms),
        )
    except HistoryNotFoundError:
        raise camera_not_found(camera_id) from None
    except HistoryBusyError:
        raise camera_busy(camera_id) from None
    if not report.complete:
        backend.capabilities["recovery"] = "DEGRADED"
    return HistoryDeleted(
        faces=report.faces, encounters=report.encounters, complete=report.complete
    )
