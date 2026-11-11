"""camera sources: the CAMERA kind, its device metadata, the camera session job

Delegated decision 2026-11-11 (M7 step 1, plan C1 to C3; PERSISTENCE_IMPLEMENTATION.md sections 4.2,
4.3 and 15):

1. `sources.kind` gains `CAMERA`, and `sources.original_artifact_id` becomes nullable for a camera
   only: `ck_sources_original_unless_camera` requires `(kind = 'CAMERA') = (original_artifact_id IS
   NULL)`, so every image and video keeps its original and a camera never has one (the ERD's "Camera
   Sources are exempt").
2. `camera_source_metadata`: one row per camera Source (`source_id` primary key, `CASCADE`) naming the
   device, `device_name` (non-blank) and an optional `device_path` (non-blank when set).
3. `jobs.type` gains `PROCESS_CAMERA_SESSION`.

SQLite cannot change a CHECK or a NOT NULL in place, so `sources` and `jobs` are recreated (batch
mode, from frozen definitions: `sources` as revision 0001 created it, `jobs` as revision 0007 left
it). Every row is kept, and every existing row satisfies the new rules (they only widen what is
allowed, and every existing source has its original).

A downgrade drops the camera table and restores the narrower `sources` and `jobs`. It is refused by
the downgrade guard while the library holds data, and with the override it is refused atomically by
the older CHECKs and the NOT NULL while a camera Source or a camera session job exists.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out here, not imported: a revision describes the schema as it was.
JOB_TYPES_BEFORE = (
    "PROCESS_SOURCE",
    "REPROCESS_SOURCE",
    "REBUILD_INDEX",
    "RETRAIN_MODEL",
    "INSTALL_RUNTIME",
    "CLEAN_STORAGE",
)
JOB_TYPES_AFTER = (*JOB_TYPES_BEFORE, "PROCESS_CAMERA_SESSION")
PRIORITIES = ("INTERACTIVE", "HIGH", "NORMAL", "LOW", "MAINTENANCE")
ORIGINAL_UNLESS_CAMERA = "(kind = 'CAMERA') = (original_artifact_id IS NULL)"


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _metadata(*referenced: str) -> sa.MetaData:
    metadata = sa.MetaData()
    for name in referenced:  # a foreign key needs its target table in the same MetaData
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    return metadata


def _sources(*, camera: bool) -> sa.Table:
    """`sources` as revision 0001 created it, or with the camera rules."""
    utc = backend.infrastructure.db.types.UTCDateTime
    kinds = ("IMAGE", "VIDEO", "CAMERA") if camera else ("IMAGE", "VIDEO")
    checks = [sa.CheckConstraint(_in("kind", kinds), name=op.f("ck_sources_kind"))]
    if camera:
        checks.append(
            sa.CheckConstraint(
                ORIGINAL_UNLESS_CAMERA, name=op.f("ck_sources_original_unless_camera")
            )
        )
    table = sa.Table(
        "sources",
        _metadata("artifacts", "processing_runs"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("original_artifact_id", sa.Uuid(), nullable=camera),
        sa.Column("thumbnail_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("current_processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", utc(), nullable=True),
        sa.Column("media_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_rate_num", sa.Integer(), nullable=True),
        sa.Column("frame_rate_den", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("updated_at", utc(), nullable=False),
        sa.Column("recycled_at", utc(), nullable=True),
        *checks,
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'RECYCLED', 'DELETING', 'DELETED', 'UNAVAILABLE')",
            name=op.f("ck_sources_state"),
        ),
        *(
            sa.CheckConstraint(
                f"{column} IS NULL OR {column} >= 0",
                name=op.f(f"ck_sources_{column}_non_negative"),
            )
            for column in (
                "frame_rate_den",
                "frame_rate_num",
                "height",
                "media_duration_ms",
                "width",
            )
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name=op.f("ck_sources_display_name_not_empty")
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_sources_revision_positive")),
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
    sa.Index(op.f("ix_sources_current_processing_run_id"), table.c.current_processing_run_id)
    sa.Index(op.f("ix_sources_original_artifact_id"), table.c.original_artifact_id)
    sa.Index(op.f("ix_sources_state_created_at_id"), table.c.state, table.c.created_at, table.c.id)
    return table


def _jobs(types: Sequence[str]) -> sa.Table:
    """`jobs` as revision 0007 left it, with the given type set."""
    utc = backend.infrastructure.db.types.UTCDateTime
    rank_check = (
        "priority_rank = CASE priority "
        + " ".join(f"WHEN '{name}' THEN {rank}" for rank, name in enumerate(PRIORITIES))
        + " ELSE priority_rank END"
    )
    table = sa.Table(
        "jobs",
        _metadata("processing_runs"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("previous_job_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("progress_mode", sa.String(), nullable=False),
        sa.Column("progress_completed", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", utc(), nullable=True),
        sa.Column("heartbeat_at", utc(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("updated_at", utc(), nullable=False),
        sa.Column("started_at", utc(), nullable=True),
        sa.Column("ended_at", utc(), nullable=True),
        sa.CheckConstraint(_in("priority", PRIORITIES), name=op.f("ck_jobs_priority")),
        sa.CheckConstraint(
            "progress_mode IN ('DETERMINATE', 'INDETERMINATE')", name=op.f("ck_jobs_progress_mode")
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'CANCELLED',"
            " 'COMPLETED', 'FAILED', 'INTERRUPTED')",
            name=op.f("ck_jobs_state"),
        ),
        sa.CheckConstraint(_in("type", types), name=op.f("ck_jobs_type")),
        sa.CheckConstraint("attempt_number >= 1", name=op.f("ck_jobs_attempt_number_positive")),
        sa.CheckConstraint(
            "progress_completed IS NULL OR progress_completed >= 0",
            name=op.f("ck_jobs_completed_non_negative"),
        ),
        sa.CheckConstraint(
            "progress_completed IS NULL OR progress_total IS NULL"
            " OR progress_completed <= progress_total",
            name=op.f("ck_jobs_completed_within_total"),
        ),
        sa.CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0", name=op.f("ck_jobs_total_non_negative")
        ),
        sa.CheckConstraint(rank_check, name=op.f("ck_jobs_priority_rank_matches_priority")),
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
    sa.Index(op.f("ix_jobs_lease_expires_at"), table.c.lease_expires_at)
    sa.Index(op.f("ix_jobs_processing_run_id"), table.c.processing_run_id)
    sa.Index(
        op.f("ix_jobs_state_priority_rank_created_at"),
        table.c.state,
        table.c.priority_rank,
        table.c.created_at,
    )
    return table


def upgrade() -> None:
    with op.batch_alter_table("sources", recreate="always", copy_from=_sources(camera=True)):
        pass
    with op.batch_alter_table("jobs", recreate="always", copy_from=_jobs(JOB_TYPES_AFTER)):
        pass
    op.create_table(
        "camera_source_metadata",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("device_name", sa.String(), nullable=False),
        sa.Column("device_path", sa.String(), nullable=True),
        sa.CheckConstraint(
            "length(trim(device_name)) > 0",
            name=op.f("ck_camera_source_metadata_device_name_not_empty"),
        ),
        sa.CheckConstraint(
            "device_path IS NULL OR length(trim(device_path)) > 0",
            name=op.f("ck_camera_source_metadata_device_path_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_camera_source_metadata_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", name=op.f("pk_camera_source_metadata")),
    )


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    op.drop_table("camera_source_metadata")
    with op.batch_alter_table("jobs", recreate="always", copy_from=_jobs(JOB_TYPES_BEFORE)):
        pass
    with op.batch_alter_table("sources", recreate="always", copy_from=_sources(camera=False)):
        pass
