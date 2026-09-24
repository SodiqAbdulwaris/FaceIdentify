"""initial schema

The coherent baseline (PERSISTENCE_IMPLEMENTATION.md §27): every table, index (including the
partial ones) and CHECK/FK constraint the SQLAlchemy models define. Generated with
`alembic revision --autogenerate`, then reviewed by hand against the persistence spec's inclusion
and exclusion list (no cameras, training, search history, generic audit/event tables, ANN
generation tables or speculative feedback tables).

Revision ID: 0001
Revises:
Create Date: 2026-09-24 07:23:10.819375

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("storage_mode", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("external_path", sa.String(), nullable=True),
        sa.Column("sha256", sa.LargeBinary(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("original_filename", sa.String(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("available_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column(
            "delete_requested_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True
        ),
        sa.Column("deleted_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.CheckConstraint(
            "(storage_mode = 'MANAGED' AND storage_key IS NOT NULL AND external_path IS NULL) OR (storage_mode = 'REFERENCED' AND external_path IS NOT NULL AND storage_key IS NULL)",
            name=op.f("ck_artifacts_location"),
        ),
        sa.CheckConstraint(
            "NOT (state = 'AVAILABLE' AND storage_mode = 'MANAGED' AND (sha256 IS NULL OR size_bytes IS NULL))",
            name=op.f("ck_artifacts_available_managed_verified"),
        ),
        sa.CheckConstraint(
            "kind IN ('SOURCE_ORIGINAL', 'FACE_CROP', 'THUMBNAIL', 'MODEL_EXPORT', 'RUNTIME_PACKAGE')",
            name=op.f("ck_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'AVAILABLE', 'MISSING', 'DELETING', 'DELETE_FAILED', 'DELETED')",
            name=op.f("ck_artifacts_state"),
        ),
        sa.CheckConstraint(
            "storage_mode IN ('MANAGED', 'REFERENCED')", name=op.f("ck_artifacts_storage_mode")
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 32", name=op.f("ck_artifacts_sha256_length")
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name=op.f("ck_artifacts_size_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_artifacts_storage_key")),
    )
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artifacts_sha256"), ["sha256"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_artifacts_state_created_at"), ["state", "created_at"], unique=False
        )

    op.create_table(
        "components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_components")),
        sa.UniqueConstraint("key", name=op.f("uq_components_key")),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("recycled_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'RECYCLED', 'DELETED')", name=op.f("ck_people_state")
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name=op.f("ck_people_display_name_not_empty")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_people_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people")),
    )
    with op.batch_alter_table("people", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_people_state_normalized_name"),
            ["state", "normalized_name"],
            unique=False,
        )

    op.create_table(
        "processing_configuration_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("canonical_json", sa.JSON(), nullable=False),
        sa.Column("fingerprint_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_user_action", sa.String(), nullable=True),
        sa.CheckConstraint(
            "length(fingerprint_sha256) = 32",
            name=op.f("ck_processing_configuration_snapshots_fingerprint_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_configuration_snapshots")),
    )
    op.create_table(
        "processing_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_processing_settings_singleton")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_processing_settings_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_settings")),
    )
    op.create_table(
        "runtime_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("manifest_schema_version", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_packages")),
        sa.UniqueConstraint("key", name=op.f("uq_runtime_packages_key")),
    )
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_runtime_settings_singleton")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_runtime_settings_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_settings")),
    )
    op.create_table(
        "storage_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_storage_settings_singleton")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_storage_settings_revision_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_settings")),
    )
    op.create_table(
        "component_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_version", sa.String(), nullable=False),
        sa.Column("contract_schema_version", sa.Integer(), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            name=op.f("fk_component_versions_component_id_components"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_component_versions")),
        sa.UniqueConstraint(
            "component_id",
            "semantic_version",
            name=op.f("uq_component_versions_component_id_semantic_version"),
        ),
    )
    op.create_table(
        "runtime_package_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("runtime_package_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("installed_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("verified_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_runtime_package_installations_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_package_id"],
            ["runtime_packages.id"],
            name=op.f("fk_runtime_package_installations_runtime_package_id_runtime_packages"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_package_installations")),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("original_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("thumbnail_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("current_processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("media_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_rate_num", sa.Integer(), nullable=True),
        sa.Column("frame_rate_den", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("recycled_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint("kind IN ('IMAGE', 'VIDEO')", name=op.f("ck_sources_kind")),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'RECYCLED', 'DELETING', 'DELETED', 'UNAVAILABLE')",
            name=op.f("ck_sources_state"),
        ),
        sa.CheckConstraint(
            "frame_rate_den IS NULL OR frame_rate_den >= 0",
            name=op.f("ck_sources_frame_rate_den_non_negative"),
        ),
        sa.CheckConstraint(
            "frame_rate_num IS NULL OR frame_rate_num >= 0",
            name=op.f("ck_sources_frame_rate_num_non_negative"),
        ),
        sa.CheckConstraint(
            "height IS NULL OR height >= 0", name=op.f("ck_sources_height_non_negative")
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name=op.f("ck_sources_display_name_not_empty")
        ),
        sa.CheckConstraint(
            "media_duration_ms IS NULL OR media_duration_ms >= 0",
            name=op.f("ck_sources_media_duration_ms_non_negative"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_sources_revision_positive")),
        sa.CheckConstraint(
            "width IS NULL OR width >= 0", name=op.f("ck_sources_width_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["current_processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_sources_current_processing_run_id_processing_runs"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["original_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_sources_original_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["thumbnail_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_sources_thumbnail_artifact_id_artifacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sources_current_processing_run_id"),
            ["current_processing_run_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_sources_original_artifact_id"), ["original_artifact_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_sources_state_created_at_id"),
            ["state", "created_at", "id"],
            unique=False,
        )

    op.create_table(
        "model_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("component_version_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("precision", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("input_contract_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint("length(sha256) = 32", name=op.f("ck_model_exports_sha256_length")),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_model_exports_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["component_version_id"],
            ["component_versions.id"],
            name=op.f("fk_model_exports_component_version_id_component_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_exports")),
    )
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("requested_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("started_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("completed_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failed_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("current_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'CANCELLED', 'FINALIZING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'NOT_RESUMABLE')",
            name=op.f("ck_processing_runs_state"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_processing_runs_revision_positive")),
        sa.ForeignKeyConstraint(
            ["configuration_snapshot_id"],
            ["processing_configuration_snapshots.id"],
            name=op.f(
                "fk_processing_runs_configuration_snapshot_id_processing_configuration_snapshots"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_checkpoint_id"],
            ["processing_checkpoints.id"],
            name=op.f("fk_processing_runs_current_checkpoint_id_processing_checkpoints"),
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_processing_runs_parent_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_processing_runs_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_runs")),
        sa.UniqueConstraint(
            "configuration_snapshot_id", name=op.f("uq_processing_runs_configuration_snapshot_id")
        ),
    )
    with op.batch_alter_table("processing_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_processing_runs_source_id_created_at"),
            ["source_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_processing_runs_state_updated_at"), ["state", "updated_at"], unique=False
        )
        batch_op.create_index(
            "ix_processing_runs_transient_state",
            ["state"],
            unique=False,
            sqlite_where=sa.text(
                "state IN ('PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'FINALIZING', 'INTERRUPTED')"
            ),
        )

    op.create_table(
        "representation_spaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semantic_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("normalization", sa.String(), nullable=False),
        sa.Column("component_version_id", sa.Uuid(), nullable=False),
        sa.Column("contract_schema_version", sa.Integer(), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("deprecated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint("metric IN ('COSINE')", name=op.f("ck_representation_spaces_metric")),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'DEPRECATED')", name=op.f("ck_representation_spaces_state")
        ),
        sa.CheckConstraint(
            "dimension > 0", name=op.f("ck_representation_spaces_dimension_positive")
        ),
        sa.ForeignKeyConstraint(
            ["component_version_id"],
            ["component_versions.id"],
            name=op.f("fk_representation_spaces_component_version_id_component_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_representation_spaces")),
        sa.UniqueConstraint("semantic_key", name=op.f("uq_representation_spaces_semantic_key")),
    )
    op.create_table(
        "ann_key_sequences",
        sa.Column("representation_space_id", sa.Uuid(), nullable=False),
        sa.Column("next_ann_key", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "next_ann_key > 0", name=op.f("ck_ann_key_sequences_next_ann_key_positive")
        ),
        sa.ForeignKeyConstraint(
            ["representation_space_id"],
            ["representation_spaces.id"],
            name=op.f("fk_ann_key_sequences_representation_space_id_representation_spaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("representation_space_id", name=op.f("pk_ann_key_sequences")),
    )
    op.create_table(
        "installed_model_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_export_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("installed_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("verified_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_installed_model_exports_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_export_id"],
            ["model_exports.id"],
            name=op.f("fk_installed_model_exports_model_export_id_model_exports"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installed_model_exports")),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("previous_job_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("progress_mode", sa.String(), nullable=False),
        sa.Column("progress_completed", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("heartbeat_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("started_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("ended_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "priority IN ('INTERACTIVE', 'HIGH', 'NORMAL', 'LOW', 'MAINTENANCE')",
            name=op.f("ck_jobs_priority"),
        ),
        sa.CheckConstraint(
            "progress_mode IN ('DETERMINATE', 'INDETERMINATE')", name=op.f("ck_jobs_progress_mode")
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'CANCELLED', 'COMPLETED', 'FAILED', 'INTERRUPTED')",
            name=op.f("ck_jobs_state"),
        ),
        sa.CheckConstraint(
            "type IN ('PROCESS_SOURCE', 'REPROCESS_SOURCE', 'REBUILD_INDEX', 'RETRAIN_MODEL', 'INSTALL_RUNTIME', 'CLEAN_STORAGE')",
            name=op.f("ck_jobs_type"),
        ),
        sa.CheckConstraint("attempt_number >= 1", name=op.f("ck_jobs_attempt_number_positive")),
        sa.CheckConstraint(
            "progress_completed IS NULL OR progress_completed >= 0",
            name=op.f("ck_jobs_completed_non_negative"),
        ),
        sa.CheckConstraint(
            "progress_completed IS NULL OR progress_total IS NULL OR progress_completed <= progress_total",
            name=op.f("ck_jobs_completed_within_total"),
        ),
        sa.CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0", name=op.f("ck_jobs_total_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["previous_job_id"],
            ["jobs.id"],
            name=op.f("fk_jobs_previous_job_id_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_jobs_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_jobs_lease_expires_at"), ["lease_expires_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_jobs_processing_run_id"), ["processing_run_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_jobs_state_priority_created_at"),
            ["state", "priority", "created_at"],
            unique=False,
        )

    op.create_table(
        "recognition_calibration_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("representation_space_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["representation_space_id"],
            ["representation_spaces.id"],
            name=op.f(
                "fk_recognition_calibration_profiles_representation_space_id_representation_spaces"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recognition_calibration_profiles")),
        sa.UniqueConstraint(
            "representation_space_id",
            "version",
            name=op.f("uq_recognition_calibration_profiles_representation_space_id_version"),
        ),
    )
    op.create_table(
        "runtime_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_export_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("device_kind", sa.String(), nullable=False),
        sa.Column("variant_key", sa.String(), nullable=False),
        sa.Column("requirements_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_export_id"],
            ["model_exports.id"],
            name=op.f("fk_runtime_variants_model_export_id_model_exports"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_variants")),
    )
    op.create_table(
        "execution_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("runtime_variant_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("started_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("ended_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("ended_reason", sa.String(), nullable=True),
        sa.Column("runtime_details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "ended_reason IS NULL OR ended_reason IN ('NORMAL', 'FALLBACK', 'CUDA_OOM', 'WORKER_CRASH', 'CANCELLED', 'SHUTDOWN')",
            name=op.f("ck_execution_segments_ended_reason"),
        ),
        sa.CheckConstraint(
            "state IN ('RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'ABANDONED')",
            name=op.f("ck_execution_segments_state"),
        ),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_execution_segments_ordinal_non_negative")),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_execution_segments_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_variant_id"],
            ["runtime_variants.id"],
            name=op.f("fk_execution_segments_runtime_variant_id_runtime_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_segments")),
    )
    with op.batch_alter_table("execution_segments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_execution_segments_processing_run_id_ordinal"),
            ["processing_run_id", "ordinal"],
            unique=True,
        )
        batch_op.create_index(
            "uq_execution_segments_one_running_per_run",
            ["processing_run_id"],
            unique=True,
            sqlite_where=sa.text("state = 'RUNNING'"),
        )

    op.create_table(
        "runtime_variant_representation_spaces",
        sa.Column("runtime_variant_id", sa.Uuid(), nullable=False),
        sa.Column("representation_space_id", sa.Uuid(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["representation_space_id"],
            ["representation_spaces.id"],
            name=op.f(
                "fk_runtime_variant_representation_spaces_representation_space_id_representation_spaces"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_variant_id"],
            ["runtime_variants.id"],
            name=op.f(
                "fk_runtime_variant_representation_spaces_runtime_variant_id_runtime_variants"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "runtime_variant_id",
            "representation_space_id",
            name=op.f("pk_runtime_variant_representation_spaces"),
        ),
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("execution_segment_id", sa.Uuid(), nullable=False),
        sa.Column("face_crop_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("sequence_in_run", sa.Integer(), nullable=False),
        sa.Column("frame_index", sa.BigInteger(), nullable=True),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=True),
        sa.Column("bbox_x", sa.Float(), nullable=False),
        sa.Column("bbox_y", sa.Float(), nullable=False),
        sa.Column("bbox_width", sa.Float(), nullable=False),
        sa.Column("bbox_height", sa.Float(), nullable=False),
        sa.Column("landmarks_json", sa.JSON(), nullable=True),
        sa.Column("quality_json", sa.JSON(), nullable=True),
        sa.Column("detector_component_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("superseded_by_run_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'SUPERSEDED', 'REJECTED', 'DELETED')",
            name=op.f("ck_observations_state"),
        ),
        sa.CheckConstraint(
            "(frame_index IS NULL) = (timestamp_ms IS NULL)",
            name=op.f("ck_observations_frame_time_paired"),
        ),
        sa.CheckConstraint(
            "bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0 AND bbox_x + bbox_width <= 1 AND bbox_y + bbox_height <= 1",
            name=op.f("ck_observations_bbox_normalized"),
        ),
        sa.CheckConstraint(
            "frame_index IS NULL OR (frame_index >= 0 AND timestamp_ms >= 0)",
            name=op.f("ck_observations_frame_time_non_negative"),
        ),
        sa.CheckConstraint(
            "sequence_in_run >= 0", name=op.f("ck_observations_sequence_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["detector_component_version_id"],
            ["component_versions.id"],
            name=op.f("fk_observations_detector_component_version_id_component_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_segment_id"],
            ["execution_segments.id"],
            name=op.f("fk_observations_execution_segment_id_execution_segments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["face_crop_artifact_id"],
            ["artifacts.id"],
            name=op.f("fk_observations_face_crop_artifact_id_artifacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_observations_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_observations_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_observations_superseded_by_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
        sa.UniqueConstraint(
            "processing_run_id",
            "sequence_in_run",
            name=op.f("uq_observations_processing_run_id_sequence_in_run"),
        ),
    )
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_observations_face_crop_artifact_id"),
            ["face_crop_artifact_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_observations_source_id_state_created_at"),
            ["source_id", "state", "created_at"],
            unique=False,
        )

    op.create_table(
        "processing_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("execution_segment_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("invalidated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("invalidated_reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('INTERMEDIATE', 'FINAL')", name=op.f("ck_processing_checkpoints_kind")
        ),
        sa.CheckConstraint(
            "state IN ('VALID', 'INVALIDATED')", name=op.f("ck_processing_checkpoints_state")
        ),
        sa.CheckConstraint(
            "ordinal >= 0", name=op.f("ck_processing_checkpoints_ordinal_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["execution_segment_id"],
            ["execution_segments.id"],
            name=op.f("fk_processing_checkpoints_execution_segment_id_execution_segments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_processing_checkpoints_processing_run_id_processing_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_checkpoints")),
    )
    with op.batch_alter_table("processing_checkpoints", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_processing_checkpoints_processing_run_id_ordinal"),
            ["processing_run_id", "ordinal"],
            unique=True,
        )
        batch_op.create_index(
            "uq_processing_checkpoints_one_valid_final_per_run",
            ["processing_run_id"],
            unique=True,
            sqlite_where=sa.text("kind = 'FINAL' AND state = 'VALID'"),
        )

    op.create_table(
        "identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_by_processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("representative_observation_id", sa.Uuid(), nullable=True),
        sa.Column("merged_into_identity_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("activated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("forgotten_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "state != 'MERGED' OR merged_into_identity_id IS NOT NULL",
            name=op.f("ck_identities_merged_target"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'MERGED', 'SPLIT', 'FORGOTTEN', 'DELETED')",
            name=op.f("ck_identities_state"),
        ),
        sa.CheckConstraint(
            "merged_into_identity_id != id", name=op.f("ck_identities_not_merged_into_self")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_identities_revision_positive")),
        sa.ForeignKeyConstraint(
            ["created_by_processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_identities_created_by_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_identity_id"],
            ["identities.id"],
            name=op.f("fk_identities_merged_into_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representative_observation_id"],
            ["observations.id"],
            name=op.f("fk_identities_representative_observation_id_observations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identities")),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("subject_identity_id", sa.Uuid(), nullable=True),
        sa.Column("subject_person_id", sa.Uuid(), nullable=True),
        sa.Column("calibration_profile_id", sa.Uuid(), nullable=True),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("superseded_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('IDENTITY_CREATED', 'IDENTITY_MATCHED', 'IDENTITY_ASSIGNED_TO_PERSON', 'IDENTITY_REMOVED_FROM_PERSON', 'IDENTITY_MERGED', 'IDENTITY_SPLIT', 'IDENTITY_FORGOTTEN', 'USER_CORRECTION')",
            name=op.f("ck_evidence_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["calibration_profile_id"],
            ["recognition_calibration_profiles.id"],
            name=op.f("fk_evidence_calibration_profile_id_recognition_calibration_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_evidence_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_evidence_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_identity_id"],
            ["identities.id"],
            name=op.f("fk_evidence_subject_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_person_id"],
            ["people.id"],
            name=op.f("fk_evidence_subject_person_id_people"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_evidence_kind_created_at"), ["kind", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_evidence_processing_run_id_created_at"),
            ["processing_run_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_evidence_subject_identity_id_created_at"),
            ["subject_identity_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("representative_observation_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("start_frame", sa.BigInteger(), nullable=True),
        sa.Column("end_frame", sa.BigInteger(), nullable=True),
        sa.Column("start_timestamp_ms", sa.BigInteger(), nullable=True),
        sa.Column("end_timestamp_ms", sa.BigInteger(), nullable=True),
        sa.Column("confidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("activated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "kind != 'IMAGE' OR (start_frame IS NULL AND end_frame IS NULL AND start_timestamp_ms IS NULL AND end_timestamp_ms IS NULL)",
            name=op.f("ck_occurrences_image_has_no_range"),
        ),
        sa.CheckConstraint(
            "kind IN ('IMAGE', 'TRACK', 'SEGMENT')", name=op.f("ck_occurrences_kind")
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'SUPERSEDED', 'DELETED')",
            name=op.f("ck_occurrences_state"),
        ),
        sa.CheckConstraint(
            "start_frame IS NULL OR end_frame IS NULL OR start_frame <= end_frame",
            name=op.f("ck_occurrences_frame_range_ordered"),
        ),
        sa.CheckConstraint(
            "start_timestamp_ms IS NULL OR end_timestamp_ms IS NULL OR start_timestamp_ms <= end_timestamp_ms",
            name=op.f("ck_occurrences_time_range_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["identities.id"],
            name=op.f("fk_occurrences_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_occurrences_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representative_observation_id"],
            ["observations.id"],
            name=op.f("fk_occurrences_representative_observation_id_observations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_occurrences_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_occurrences")),
    )
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrences_identity_id_state_created_at"),
            ["identity_id", "state", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_occurrences_processing_run_id_state"),
            ["processing_run_id", "state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_occurrences_source_id_state_created_at"),
            ["source_id", "state", "created_at"],
            unique=False,
        )

    op.create_table(
        "representations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("execution_segment_id", sa.Uuid(), nullable=False),
        sa.Column("representation_space_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("ann_key", sa.BigInteger(), nullable=True),
        sa.Column("vector", sa.LargeBinary(), nullable=True),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("activated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("erased_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "(state = 'ERASED' AND vector IS NULL AND ann_key IS NULL) OR (state != 'ERASED' AND vector IS NOT NULL)",
            name=op.f("ck_representations_erasure"),
        ),
        sa.CheckConstraint(
            "state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)",
            name=op.f("ck_representations_active_eligible"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'SUPERSEDED', 'ERASED', 'DELETED')",
            name=op.f("ck_representations_state"),
        ),
        sa.CheckConstraint(
            "ann_key IS NULL OR ann_key > 0", name=op.f("ck_representations_ann_key_positive")
        ),
        sa.CheckConstraint(
            "vector IS NULL OR length(vector) = 4 * vector_dimension",
            name=op.f("ck_representations_vector_length"),
        ),
        sa.CheckConstraint(
            "vector_dimension > 0", name=op.f("ck_representations_vector_dimension_positive")
        ),
        sa.ForeignKeyConstraint(
            ["execution_segment_id"],
            ["execution_segments.id"],
            name=op.f("fk_representations_execution_segment_id_execution_segments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["identities.id"],
            name=op.f("fk_representations_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observations.id"],
            name=op.f("fk_representations_observation_id_observations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_representations_processing_run_id_processing_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representation_space_id"],
            ["representation_spaces.id"],
            name=op.f("fk_representations_representation_space_id_representation_spaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_representations")),
        sa.UniqueConstraint("ann_key", name=op.f("uq_representations_ann_key")),
        sa.UniqueConstraint(
            "observation_id",
            "representation_space_id",
            name=op.f("uq_representations_observation_id_representation_space_id"),
        ),
    )
    with op.batch_alter_table("representations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_representations_identity_id_state"),
            ["identity_id", "state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_representations_processing_run_id_state"),
            ["processing_run_id", "state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_representations_representation_space_id_state_ann_key"),
            ["representation_space_id", "state", "ann_key"],
            unique=False,
        )

    op.create_table(
        "evidence_candidates",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("representation_id", sa.Uuid(), nullable=True),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("raw_similarity", sa.Float(), nullable=False),
        sa.Column("calibrated_confidence", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("rank >= 0", name=op.f("ck_evidence_candidates_rank_non_negative")),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_evidence_candidates_evidence_id_evidence"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["identities.id"],
            name=op.f("fk_evidence_candidates_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representation_id"],
            ["representations.id"],
            name=op.f("fk_evidence_candidates_representation_id_representations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evidence_id", "rank", name=op.f("pk_evidence_candidates")),
    )
    op.create_table(
        "evidence_representations",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("representation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.CheckConstraint(
            "role IN ('SUBJECT', 'SELECTED_CANDIDATE', 'CANDIDATE', 'SUPPORTING')",
            name=op.f("ck_evidence_representations_role"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_evidence_representations_evidence_id_evidence"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["representation_id"],
            ["representations.id"],
            name=op.f("fk_evidence_representations_representation_id_representations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "evidence_id", "representation_id", "role", name=op.f("pk_evidence_representations")
        ),
    )
    op.create_table(
        "identity_lineage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_identity_id", sa.Uuid(), nullable=False),
        sa.Column("to_identity_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('MERGED_INTO', 'SPLIT_FROM')", name=op.f("ck_identity_lineage_kind")
        ),
        sa.CheckConstraint(
            "from_identity_id != to_identity_id",
            name=op.f("ck_identity_lineage_distinct_endpoints"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_identity_lineage_evidence_id_evidence"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_identity_id"],
            ["identities.id"],
            name=op.f("fk_identity_lineage_from_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_identity_id"],
            ["identities.id"],
            name=op.f("fk_identity_lineage_to_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_lineage")),
        sa.UniqueConstraint(
            "from_identity_id",
            "to_identity_id",
            "kind",
            name=op.f("uq_identity_lineage_from_identity_id_to_identity_id_kind"),
        ),
    )
    op.create_table(
        "identity_person_associations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("ended_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "(state = 'ACTIVE') = (ended_at IS NULL)",
            name=op.f("ck_identity_person_associations_ended_when_inactive"),
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'REMOVED', 'SUPERSEDED')",
            name=op.f("ck_identity_person_associations_state"),
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_identity_person_associations_revision_positive")
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name=op.f("fk_identity_person_associations_evidence_id_evidence"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["identities.id"],
            name=op.f("fk_identity_person_associations_identity_id_identities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk_identity_person_associations_person_id_people"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_person_associations")),
    )
    with op.batch_alter_table("identity_person_associations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_identity_person_associations_person_id_state"),
            ["person_id", "state"],
            unique=False,
        )
        batch_op.create_index(
            "uq_identity_person_active",
            ["identity_id"],
            unique=True,
            sqlite_where=sa.text("state = 'ACTIVE'"),
        )

    op.create_table(
        "index_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("representation_id", sa.Uuid(), nullable=False),
        sa.Column("representation_space_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("not_before_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("last_attempt_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("applied_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("created_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "operation IN ('ADD', 'REMOVE')", name=op.f("ck_index_operations_operation")
        ),
        sa.CheckConstraint(
            "state != 'APPLIED' OR applied_at IS NOT NULL",
            name=op.f("ck_index_operations_applied_has_time"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'APPLIED', 'FAILED')", name=op.f("ck_index_operations_state")
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_index_operations_attempt_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["representation_id"],
            ["representations.id"],
            name=op.f("fk_index_operations_representation_id_representations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["representation_space_id"],
            ["representation_spaces.id"],
            name=op.f("fk_index_operations_representation_space_id_representation_spaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_index_operations")),
    )
    with op.batch_alter_table("index_operations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_index_operations_representation_space_id_state"),
            ["representation_space_id", "state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_index_operations_state_not_before_at_created_at"),
            ["state", "not_before_at", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "uq_index_operations_one_pending_per_representation_operation",
            ["representation_id", "operation"],
            unique=True,
            sqlite_where=sa.text("state = 'PENDING'"),
        )

    op.create_table(
        "occurrence_observations",
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0", name=op.f("ck_occurrence_observations_ordinal_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["observations.id"],
            name=op.f("fk_occurrence_observations_observation_id_observations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["occurrences.id"],
            name=op.f("fk_occurrence_observations_occurrence_id_occurrences"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "occurrence_id", "observation_id", name=op.f("pk_occurrence_observations")
        ),
        sa.UniqueConstraint(
            "occurrence_id",
            "ordinal",
            name=op.f("uq_occurrence_observations_occurrence_id_ordinal"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("occurrence_observations")
    with op.batch_alter_table("index_operations", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_index_operations_one_pending_per_representation_operation",
            sqlite_where=sa.text("state = 'PENDING'"),
        )
        batch_op.drop_index(batch_op.f("ix_index_operations_state_not_before_at_created_at"))
        batch_op.drop_index(batch_op.f("ix_index_operations_representation_space_id_state"))

    op.drop_table("index_operations")
    with op.batch_alter_table("identity_person_associations", schema=None) as batch_op:
        batch_op.drop_index("uq_identity_person_active", sqlite_where=sa.text("state = 'ACTIVE'"))
        batch_op.drop_index(batch_op.f("ix_identity_person_associations_person_id_state"))

    op.drop_table("identity_person_associations")
    op.drop_table("identity_lineage")
    op.drop_table("evidence_representations")
    op.drop_table("evidence_candidates")
    with op.batch_alter_table("representations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_representations_representation_space_id_state_ann_key"))
        batch_op.drop_index(batch_op.f("ix_representations_processing_run_id_state"))
        batch_op.drop_index(batch_op.f("ix_representations_identity_id_state"))

    op.drop_table("representations")
    with op.batch_alter_table("occurrences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_occurrences_source_id_state_created_at"))
        batch_op.drop_index(batch_op.f("ix_occurrences_processing_run_id_state"))
        batch_op.drop_index(batch_op.f("ix_occurrences_identity_id_state_created_at"))

    op.drop_table("occurrences")
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_subject_identity_id_created_at"))
        batch_op.drop_index(batch_op.f("ix_evidence_processing_run_id_created_at"))
        batch_op.drop_index(batch_op.f("ix_evidence_kind_created_at"))

    op.drop_table("evidence")
    op.drop_table("identities")
    with op.batch_alter_table("processing_checkpoints", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_processing_checkpoints_one_valid_final_per_run",
            sqlite_where=sa.text("kind = 'FINAL' AND state = 'VALID'"),
        )
        batch_op.drop_index(batch_op.f("ix_processing_checkpoints_processing_run_id_ordinal"))

    op.drop_table("processing_checkpoints")
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_observations_source_id_state_created_at"))
        batch_op.drop_index(batch_op.f("ix_observations_face_crop_artifact_id"))

    op.drop_table("observations")
    op.drop_table("runtime_variant_representation_spaces")
    with op.batch_alter_table("execution_segments", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_execution_segments_one_running_per_run", sqlite_where=sa.text("state = 'RUNNING'")
        )
        batch_op.drop_index(batch_op.f("ix_execution_segments_processing_run_id_ordinal"))

    op.drop_table("execution_segments")
    op.drop_table("runtime_variants")
    op.drop_table("recognition_calibration_profiles")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_state_priority_created_at"))
        batch_op.drop_index(batch_op.f("ix_jobs_processing_run_id"))
        batch_op.drop_index(batch_op.f("ix_jobs_lease_expires_at"))

    op.drop_table("jobs")
    op.drop_table("installed_model_exports")
    op.drop_table("ann_key_sequences")
    op.drop_table("representation_spaces")
    with op.batch_alter_table("processing_runs", schema=None) as batch_op:
        batch_op.drop_index(
            "ix_processing_runs_transient_state",
            sqlite_where=sa.text(
                "state IN ('PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'FINALIZING', 'INTERRUPTED')"
            ),
        )
        batch_op.drop_index(batch_op.f("ix_processing_runs_state_updated_at"))
        batch_op.drop_index(batch_op.f("ix_processing_runs_source_id_created_at"))

    op.drop_table("processing_runs")
    op.drop_table("model_exports")
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sources_state_created_at_id"))
        batch_op.drop_index(batch_op.f("ix_sources_original_artifact_id"))
        batch_op.drop_index(batch_op.f("ix_sources_current_processing_run_id"))

    op.drop_table("sources")
    op.drop_table("runtime_package_installations")
    op.drop_table("component_versions")
    op.drop_table("storage_settings")
    op.drop_table("runtime_settings")
    op.drop_table("runtime_packages")
    op.drop_table("processing_settings")
    op.drop_table("processing_configuration_snapshots")
    with op.batch_alter_table("people", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_people_state_normalized_name"))

    op.drop_table("people")
    op.drop_table("components")
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifacts_state_created_at"))
        batch_op.drop_index(batch_op.f("ix_artifacts_sha256"))

    op.drop_table("artifacts")
