"""Runtime, component and package metadata (PERSISTENCE_IMPLEMENTATION.md §18).

Hierarchy: Component -> ComponentVersion -> ModelExport -> RuntimeVariant, alongside
RepresentationSpace (see `backend.app.memory.models`), RecognitionCalibrationProfile and
RuntimePackage. Metadata rows are retained after uninstall; only installation rows change.

Open questions (no spec defines the complete value sets, so these are unconstrained strings for
now; see .agents/CONTEXT.md): the `state` columns of every catalog table, and
`ModelExport.format`/`precision` and `RuntimeVariant.provider`/`device_kind`. The API contract
gives only examples (ONNX/TensorRT, FP32/FP16/INT8, CUDA/DirectML/CPU). The package-membership
association tables are deferred: §18 adds them "only when the trusted manifest needs relational
querying".
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime, enum_check, uuid_pk


class ComponentKind(StrEnum):
    """Logical ML capabilities named in API and Contracts §73."""

    FACE_DETECTOR = "FACE_DETECTOR"
    FACE_REPRESENTATION = "FACE_REPRESENTATION"
    FACE_QUALITY = "FACE_QUALITY"


class Component(Base):
    """A logical capability; CUDA and CPU implementations are not separate components."""

    __tablename__ = "components"
    __table_args__ = (enum_check("kind", ComponentKind),)

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)


class ComponentVersion(Base):
    """An immutable semantic implementation, including its pre/postprocessing contract."""

    __tablename__ = "component_versions"
    __table_args__ = (UniqueConstraint("component_id", "semantic_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    component_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("components.id", ondelete="RESTRICT")
    )
    semantic_version: Mapped[str] = mapped_column(String)
    contract_schema_version: Mapped[int] = mapped_column(Integer)
    contract_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ModelExport(Base):
    """An immutable executable artifact description (e.g. ONNX FP16)."""

    __tablename__ = "model_exports"
    __table_args__ = (CheckConstraint("length(sha256) = 32", name="sha256_length"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    component_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="RESTRICT")
    )
    format: Mapped[str] = mapped_column(String)
    precision: Mapped[str] = mapped_column(String)
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    sha256: Mapped[bytes] = mapped_column(LargeBinary)
    input_contract_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class InstalledModelExport(Base):
    """Local byte/installation state of a model export."""

    __tablename__ = "installed_model_exports"

    id: Mapped[uuid.UUID] = uuid_pk()
    model_export_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_exports.id", ondelete="RESTRICT")
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String)
    installed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_detail: Mapped[str | None] = mapped_column(String)


class RuntimeVariant(Base):
    """How an export is executed (e.g. ONNX FP16 + CUDA); not semantic model identity."""

    __tablename__ = "runtime_variants"

    id: Mapped[uuid.UUID] = uuid_pk()
    model_export_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_exports.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String)
    device_kind: Mapped[str] = mapped_column(String)
    variant_key: Mapped[str] = mapped_column(String, unique=True)
    requirements_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String)


class RuntimeVariantRepresentationSpace(Base):
    """Explicit, validated compatibility between a runtime variant and a representation space."""

    __tablename__ = "runtime_variant_representation_spaces"

    # CASCADE: compatibility rows are owned by both sides (§20).
    runtime_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_variants.id", ondelete="CASCADE"), primary_key=True
    )
    representation_space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation_spaces.id", ondelete="CASCADE"), primary_key=True
    )
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String)


class RecognitionCalibrationProfile(Base):
    """Immutable interpretation of similarity for one space. A change creates a new profile."""

    __tablename__ = "recognition_calibration_profiles"
    __table_args__ = (UniqueConstraint("representation_space_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    representation_space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation_spaces.id", ondelete="RESTRICT")
    )
    version: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    schema_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RuntimePackage(Base):
    """Trusted installable bundle metadata."""

    __tablename__ = "runtime_packages"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String, unique=True)
    manifest_schema_version: Mapped[int] = mapped_column(Integer)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RuntimePackageInstallation(Base):
    """Local installation state of a runtime package."""

    __tablename__ = "runtime_package_installations"

    id: Mapped[uuid.UUID] = uuid_pk()
    runtime_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_packages.id", ondelete="RESTRICT")
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String)
    installed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_detail: Mapped[str | None] = mapped_column(String)
