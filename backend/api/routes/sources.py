"""Sources: import an image, list and read sources, serve a source's original (API section 5, 21,
22, 29 and 30; M4 W3.2).

Routes are thin: each calls a use case or a repository and shapes the result as an API schema
(never a database row, never a filesystem path). They are plain `def`, so FastAPI runs the blocking
database and file work in a worker thread and the event loop stays free.

* `POST /sources/import` takes a path on this machine (the shell's native file picker supplies it;
  the sidecar is loopback-only and token-authenticated). `MANAGED` copies the bytes into the
  library, `REFERENCED` records a verified reference to the user's own file and never touches it.
  Import creates the source; it does not process it.
* The list is keyset-paginated, newest first, with the unique id as the tie-breaker.
* `GET /sources/{id}/media` streams the source's own original, with a content type and an ETag (its
  SHA-256), and answers `304` to a matching `If-None-Match`. It serves nothing else: the bytes come
  from the source's original artifact, never from a path the client names.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.pagination import (
    Page,
    PageInfo,
    PageQuery,
    decode_cursor,
    encode_cursor,
    invalid_cursor,
)
from backend.api.startup import Backend, MediaLimits
from backend.app.processing.models import ProcessingRun
from backend.app.sources.import_source import (
    ImportedSource,
    ImportFileError,
    ImportFileTooLargeError,
    ImportSourceUseCase,
)
from backend.app.sources.models import Artifact, ArtifactState, Source, StorageMode
from backend.app.sources.repository import LibraryCursor, SourceRepository
from backend.infrastructure.media.image import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedImageError,
)
from backend.infrastructure.storage.files import BytesMissingError
from backend.infrastructure.storage.referenced import ReferencedFileError

router = APIRouter(prefix="/sources", tags=["sources"])

NOT_PROCESSED = "NOT_PROCESSED"
_CHUNK = 64 * 1024


# --- schemas --------------------------------------------------------------------------------


class MediaReference(BaseModel):
    """Media is referenced, never embedded or located by a path (API section 22)."""

    id: str
    kind: str
    url: str
    content_type: str | None


class ProcessingRunBrief(BaseModel):
    id: str
    state: str


class SourceSummary(BaseModel):
    id: str
    type: str
    display_name: str
    availability: str
    processing_status: str
    thumbnail: MediaReference | None
    created_at: datetime
    updated_at: datetime


class SourceDetail(SourceSummary):
    state: str
    storage_mode: str
    original: MediaReference | None
    width: int | None
    height: int | None
    mime_type: str | None
    size_bytes: int | None
    original_filename: str | None
    latest_processing_run: ProcessingRunBrief | None
    recycled_at: datetime | None


class ImportRequest(BaseModel):
    path: str = Field(min_length=1)
    storage_mode: Literal["MANAGED", "REFERENCED"] = "MANAGED"
    display_name: str | None = None

    @field_validator("path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("an import path must be absolute")
        return value


# --- shaping --------------------------------------------------------------------------------


def _original_reference(source: Source, artifact: Artifact) -> MediaReference | None:
    if artifact.state != ArtifactState.AVAILABLE:
        return None
    return MediaReference(
        id=str(source.id),
        kind="ORIGINAL",
        url=f"/api/v1/sources/{source.id}/media",
        content_type=artifact.mime_type,
    )


def _latest_runs(session: Session, source_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProcessingRun]:
    rows = session.scalars(
        select(ProcessingRun)
        .where(ProcessingRun.source_id.in_(source_ids))
        .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
    )
    latest: dict[uuid.UUID, ProcessingRun] = {}
    for run in rows:
        latest.setdefault(run.source_id, run)
    return latest


def _summary(source: Source, artifact_state: str, run: ProcessingRun | None) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "type": source.kind,
        "display_name": source.display_name,
        "availability": artifact_state,
        "processing_status": NOT_PROCESSED if run is None else run.state,
        "thumbnail": None,  # no thumbnails are generated yet
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def _detail(source: Source, artifact: Artifact, run: ProcessingRun | None) -> SourceDetail:
    return SourceDetail(
        **_summary(source, artifact.state, run),
        state=source.state,
        storage_mode=artifact.storage_mode,
        original=_original_reference(source, artifact),
        width=source.width,
        height=source.height,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        original_filename=artifact.original_filename,
        latest_processing_run=None
        if run is None
        else ProcessingRunBrief(id=str(run.id), state=run.state),
        recycled_at=source.recycled_at,
    )


def _source_detail(session: Session, source_id: uuid.UUID) -> SourceDetail:
    row = session.execute(
        select(Source, Artifact)
        .join(Artifact, Artifact.id == Source.original_artifact_id)
        .where(Source.id == source_id)
    ).one_or_none()
    if row is None:
        raise source_not_found(source_id)
    source, artifact = row
    return _detail(source, artifact, _latest_runs(session, [source_id]).get(source_id))


def source_not_found(source_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "SOURCE_NOT_FOUND", "The requested source could not be found.",
        details={"source_id": str(source_id)},
    )  # fmt: skip


def media_limits(backend: Annotated[Backend, Depends(get_backend)]) -> MediaLimits:
    if backend.media_limits is None:
        raise ApiError(503, "IMPORT_UNAVAILABLE", "Importing is not configured.")
    return backend.media_limits


# --- routes ---------------------------------------------------------------------------------


@router.post("/import", status_code=201)
def import_source(
    body: ImportRequest,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
    limits: Annotated[MediaLimits, Depends(media_limits)],
) -> SourceDetail:
    use_case = ImportSourceUseCase(
        library.unit_of_work,
        library.store,
        new_id=backend.settings.new_id,
        clock=backend.settings.clock,
        max_pixels=limits.max_pixels,
        max_bytes=limits.max_bytes,
    )
    path = Path(body.path)
    try:
        imported: ImportedSource = (
            use_case.import_managed(path, display_name=body.display_name)
            if body.storage_mode == "MANAGED"
            else use_case.import_referenced(path, display_name=body.display_name)
        )
    except ImportFileTooLargeError:
        raise ApiError(
            413, "SOURCE_FILE_TOO_LARGE", "The file is larger than is allowed."
        ) from None
    except ImportFileError:
        raise ApiError(400, "SOURCE_FILE_UNREADABLE", "The file could not be read.") from None
    except ReferencedFileError:
        raise ApiError(400, "REFERENCED_FILE_INVALID", "The file cannot be referenced.") from None
    except UnsupportedImageError:
        raise ApiError(
            415, "MEDIA_FORMAT_UNSUPPORTED", "Only JPEG, PNG, BMP and WebP images are supported."
        ) from None
    except CorruptImageError:
        raise ApiError(422, "MEDIA_CORRUPT", "The image could not be read.") from None
    except ImageTooLargeError:
        raise ApiError(
            413, "MEDIA_TOO_LARGE", "The image has more pixels than is allowed."
        ) from None
    except ValueError:  # a blank display name: the only ValueError the use case raises itself
        raise ApiError(
            422, "VALIDATION_ERROR", "The request is not valid.",
            details={"fields": [{"location": ["body", "display_name"], "type": "value_error"}]},
        ) from None  # fmt: skip
    return library.unit_of_work.read(lambda session: _source_detail(session, imported.source_id))


def _cursor_after(cursor: str | None, context: str) -> LibraryCursor | None:
    if cursor is None:
        return None
    key = decode_cursor(cursor, context)
    try:
        return LibraryCursor(datetime.fromisoformat(key[0]), uuid.UUID(key[1]))
    except (IndexError, TypeError, ValueError):
        raise invalid_cursor() from None


@router.get("")
def list_sources(
    library: Library,
    page: PageQuery,
    state: Annotated[Literal["ACTIVE", "RECYCLED"], Query()] = "ACTIVE",
) -> Page[SourceSummary]:
    context = f"sources:{state}"
    after = _cursor_after(page.cursor, context)

    def read(session: Session) -> Page[SourceSummary]:
        result = SourceRepository(session).library_page(state=state, limit=page.limit, after=after)
        latest = _latest_runs(session, [entry.source.id for entry in result.entries])
        items = [
            SourceSummary(**_summary(e.source, e.original_state, latest.get(e.source.id)))
            for e in result.entries
        ]
        next_cursor = (
            None
            if result.next_cursor is None
            else encode_cursor(
                context, [result.next_cursor.created_at.isoformat(), str(result.next_cursor.id)]
            )
        )
        return Page(
            items=items, page=PageInfo(next_cursor=next_cursor, has_more=next_cursor is not None)
        )

    return library.unit_of_work.read(read)


@router.get("/{source_id}")
def get_source(source_id: uuid.UUID, library: Library) -> SourceDetail:
    return library.unit_of_work.read(lambda session: _source_detail(session, source_id))


@router.get("/{source_id}/media", response_model=None)
def source_media(
    source_id: uuid.UUID,
    library: Library,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    def find(session: Session) -> Artifact:
        artifact = session.execute(
            select(Artifact)
            .join(Source, Source.original_artifact_id == Artifact.id)
            .where(Source.id == source_id)
        ).scalar_one_or_none()
        if artifact is None:
            raise source_not_found(source_id)
        session.expunge(artifact)  # a plain, detached row: nothing lazy is read after the session
        return artifact

    artifact = library.unit_of_work.read(find)
    if artifact.state != ArtifactState.AVAILABLE:
        raise ApiError(
            404, "SOURCE_FILE_MISSING", "The original file is not available.",
            details={"availability": artifact.state},
        )  # fmt: skip
    etag = f'"{artifact.sha256.hex()}"' if artifact.sha256 is not None else None
    headers = {"Cache-Control": "private, no-cache"}
    if etag is not None:
        headers["ETag"] = etag
        if if_none_match is not None and _matches(etag, if_none_match):
            return Response(status_code=304, headers=headers)
    try:
        stream = _open_original(library, artifact)
    except (BytesMissingError, OSError):
        raise ApiError(
            404, "SOURCE_FILE_MISSING", "The original file is not available.",
            details={"availability": "MISSING"},
        ) from None  # fmt: skip
    return StreamingResponse(
        _chunks(stream),
        media_type=artifact.mime_type or "application/octet-stream",
        headers=headers,
    )


def _matches(etag: str, if_none_match: str) -> bool:
    """`If-None-Match` uses weak comparison (RFC 9110 section 13.1.2): `*` and `W/` forms match."""
    offered = [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]
    return "*" in offered or etag in offered


def _open_original(library: Any, artifact: Artifact) -> BinaryIO:
    if artifact.storage_mode == StorageMode.MANAGED:
        assert artifact.storage_key is not None  # a MANAGED artifact always has a key (CHECK)
        return library.store.open(artifact.storage_key)  # type: ignore[no-any-return]
    assert artifact.external_path is not None  # a REFERENCED artifact always has a path (CHECK)
    return Path(artifact.external_path).open("rb")


def _chunks(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := stream.read(_CHUNK):
            yield chunk
    finally:
        stream.close()
