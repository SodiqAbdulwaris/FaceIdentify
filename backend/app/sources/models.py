"""Artifact and Source persistence (PERSISTENCE_IMPLEMENTATION.md §4)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk


class ArtifactKind(StrEnum):
    SOURCE_ORIGINAL = "SOURCE_ORIGINAL"
    FACE_CROP = "FACE_CROP"
    THUMBNAIL = "THUMBNAIL"
    MODEL_EXPORT = "MODEL_EXPORT"
    RUNTIME_PACKAGE = "RUNTIME_PACKAGE"


class StorageMode(StrEnum):
    MANAGED = "MANAGED"
    REFERENCED = "REFERENCED"


class ArtifactState(StrEnum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    DELETING = "DELETING"
    DELETE_FAILED = "DELETE_FAILED"
    DELETED = "DELETED"


class Artifact(Base):
    """One file-like byte resource. Never exposes an absolute path to the frontend."""

    __tablename__ = "artifacts"
    __table_args__ = (
        enum_check("kind", ArtifactKind),
        enum_check("storage_mode", StorageMode),
        enum_check("state", ArtifactState),
        # Exactly one location form: MANAGED has a logical key, REFERENCED an external path.
        CheckConstraint(
            "(storage_mode = 'MANAGED' AND storage_key IS NOT NULL AND external_path IS NULL)"
            " OR (storage_mode = 'REFERENCED' AND external_path IS NOT NULL"
            " AND storage_key IS NULL)",
            name="location",
        ),
        # Verified managed content must carry its hash and size.
        CheckConstraint(
            "NOT (state = 'AVAILABLE' AND storage_mode = 'MANAGED'"
            " AND (sha256 IS NULL OR size_bytes IS NULL))",
            name="available_managed_verified",
        ),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 32", name="sha256_length"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_non_negative"),
        Index(None, "state", "created_at"),
        Index(None, "sha256"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String)
    storage_mode: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str | None] = mapped_column(String, unique=True)
    external_path: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String)
    original_filename: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delete_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_code: Mapped[str | None] = mapped_column(String)
    failure_detail: Mapped[str | None] = mapped_column(String)


class SourceKind(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class SourceState(StrEnum):
    ACTIVE = "ACTIVE"
    RECYCLED = "RECYCLED"
    DELETING = "DELETING"
    DELETED = "DELETED"
    UNAVAILABLE = "UNAVAILABLE"


class Source(Base):
    """A user-facing imported image or video. Owns its library lifecycle, not its bytes."""

    __tablename__ = "sources"
    __table_args__ = (
        enum_check("kind", SourceKind),
        enum_check("state", SourceState),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_empty"),
        *(
            CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"{column}_non_negative")
            for column in (
                "media_duration_ms",
                "width",
                "height",
                "frame_rate_num",
                "frame_rate_den",
            )
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(None, "state", "created_at", "id"),
        Index(None, "current_processing_run_id"),
        Index(None, "original_artifact_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    original_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT")
    )
    thumbnail_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    # Circular with processing_runs.source_id; use_alter breaks the create-order cycle.
    current_processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="SET NULL", use_alter=True)
    )
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    media_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    frame_rate_num: Mapped[int | None] = mapped_column(Integer)
    frame_rate_den: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recycled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
