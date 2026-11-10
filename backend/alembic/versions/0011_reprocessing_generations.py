"""reprocessing generations: the supersession link, superseded timestamps, two Evidence kinds

Owner decision 2026-11-09 (D1; M6 step 1, issue 180): PERSISTENCE_IMPLEMENTATION.md section 12.1
item 1 and sections 5, 6.2, 10 and 11.

1. `processing_runs.supersedes_run_id`: a nullable self-reference (`RESTRICT`) naming the run a
   reprocess run replaces, never the run itself (`ck_processing_runs_supersedes_not_self`), and a
   partial unique index so that a run is superseded by at most one `COMPLETED` run.
2. `observations`, `representations` and `occurrences` gain a nullable `superseded_at`, required
   whenever the row is `SUPERSEDED` (an observation also needs its `superseded_by_run_id`).
3. The `evidence.kind` CHECK gains `REPROCESS_DECISION_CARRIED_OVER` and
   `REPROCESS_REVIEW_REQUIRED`.

No state set changes. SQLite cannot add a CHECK or a named foreign key in place, so the five tables
are recreated (batch mode, from frozen definitions of their shape before this revision: see
revisions 0002 and 0005). The snapshot delete trigger names `processing_runs`, so it is dropped while
that table is rebuilt and recreated, byte-identical, straight after. Every row is kept: the new columns are NULL, and nothing before this
revision ever set a row `SUPERSEDED`, so no existing database can violate the new CHECKs.

A downgrade recreates the five tables in their earlier shape, dropping the new columns. It is
refused by the downgrade guard while the library holds data, and with the override it is refused
atomically by the older `evidence.kind` CHECK while a reprocessing Evidence row exists.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_BEFORE = (
    "IDENTITY_CREATED",
    "IDENTITY_MATCHED",
    "RECOGNITION_ABSTAINED",
    "IDENTITY_ASSIGNED_TO_PERSON",
    "IDENTITY_REMOVED_FROM_PERSON",
    "IDENTITY_MERGED",
    "IDENTITY_SPLIT",
    "IDENTITY_FORGOTTEN",
    "USER_CORRECTION",
    "PERSON_RENAMED",
    "SOURCE_PERMANENTLY_DELETED",
)
KINDS_AFTER = (*KINDS_BEFORE, "REPROCESS_DECISION_CARRIED_OVER", "REPROCESS_REVIEW_REQUIRED")

SUPERSEDES_FK = "fk_processing_runs_supersedes_run_id_processing_runs"
SUPERSEDES_NOT_SELF = "supersedes_run_id IS NULL OR supersedes_run_id != id"
ONE_COMPLETED_SUPERSEDER = "uq_processing_runs_one_completed_superseder"
OBSERVATION_SUPERSEDED = (
    "state != 'SUPERSEDED' OR (superseded_at IS NOT NULL AND superseded_by_run_id IS NOT NULL)"
)
SUPERSEDED_HAS_TIME = "state != 'SUPERSEDED' OR superseded_at IS NOT NULL"
# A copy of `SNAPSHOT_NO_DELETE_WHILE_USED_TRIGGER` in `backend/app/processing/models.py` (as frozen
# in revision 0003): it names `processing_runs`, so SQLite refuses to rename a rebuilt
# `processing_runs` into place while it exists. It is dropped for the rebuild and recreated after.
SNAPSHOT_TRIGGER = "trg_processing_configuration_snapshots_no_delete_while_used"
SNAPSHOT_TRIGGER_SQL = (
    "CREATE TRIGGER trg_processing_configuration_snapshots_no_delete_while_used "
    "BEFORE DELETE ON processing_configuration_snapshots "
    "WHEN EXISTS (SELECT 1 FROM processing_runs WHERE configuration_snapshot_id = OLD.id) "
    "BEGIN SELECT RAISE(ABORT, 'a processing configuration snapshot that a run uses cannot be "
    "deleted'); END"
)
TRANSIENT_RUN_STATES = (
    "state IN ('PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'FINALIZING',"
    " 'INTERRUPTED')"
)


def _metadata(*referenced: str) -> sa.MetaData:
    metadata = sa.MetaData()
    for name in referenced:  # a foreign key needs its target table in the same MetaData
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    return metadata


def _processing_runs() -> sa.Table:
    """`processing_runs` as `0001` created it."""
    metadata = _metadata("processing_checkpoints", "processing_configuration_snapshots", "sources")
    utc = backend.infrastructure.db.types.UTCDateTime
    return sa.Table(
        "processing_runs",
        metadata,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("requested_at", utc(), nullable=False),
        sa.Column("started_at", utc(), nullable=True),
        sa.Column("completed_at", utc(), nullable=True),
        sa.Column("failed_at", utc(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.Column("current_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("updated_at", utc(), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'CANCELLED',"
            " 'FINALIZING', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'NOT_RESUMABLE')",
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
        sa.Index(op.f("ix_processing_runs_source_id_created_at"), "source_id", "created_at"),
        sa.Index(op.f("ix_processing_runs_state_updated_at"), "state", "updated_at"),
        sa.Index(
            "ix_processing_runs_transient_state",
            "state",
            sqlite_where=sa.text(TRANSIENT_RUN_STATES),
        ),
    )


def _observations() -> sa.Table:
    """`observations` as `0005` left it."""
    metadata = _metadata(
        "artifacts",
        "component_versions",
        "execution_segments",
        "processing_runs",
        "runtime_variants",
        "sources",
    )
    utc = backend.infrastructure.db.types.UTCDateTime
    return sa.Table(
        "observations",
        metadata,
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
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("superseded_by_run_id", sa.Uuid(), nullable=True),
        sa.Column("runtime_variant_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'SUPERSEDED', 'REJECTED', 'DELETED')",
            name=op.f("ck_observations_state"),
        ),
        sa.CheckConstraint(
            "(frame_index IS NULL) = (timestamp_ms IS NULL)",
            name=op.f("ck_observations_frame_time_paired"),
        ),
        sa.CheckConstraint(
            "bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0"
            " AND bbox_x + bbox_width <= 1 AND bbox_y + bbox_height <= 1",
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
        sa.ForeignKeyConstraint(
            ["runtime_variant_id"],
            ["runtime_variants.id"],
            name=op.f("fk_observations_runtime_variant_id_runtime_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
        sa.UniqueConstraint(
            "processing_run_id",
            "sequence_in_run",
            name=op.f("uq_observations_processing_run_id_sequence_in_run"),
        ),
        sa.Index(op.f("ix_observations_face_crop_artifact_id"), "face_crop_artifact_id"),
        sa.Index(
            op.f("ix_observations_source_id_state_created_at"), "source_id", "state", "created_at"
        ),
    )


def _representations() -> sa.Table:
    """`representations` as `0005` left it."""
    metadata = _metadata(
        "execution_segments",
        "identities",
        "observations",
        "processing_runs",
        "representation_spaces",
        "runtime_variants",
    )
    utc = backend.infrastructure.db.types.UTCDateTime
    return sa.Table(
        "representations",
        metadata,
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
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("activated_at", utc(), nullable=True),
        sa.Column("erased_at", utc(), nullable=True),
        sa.Column("runtime_variant_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(state = 'ERASED' AND vector IS NULL AND ann_key IS NULL)"
            " OR (state != 'ERASED' AND vector IS NOT NULL)",
            name=op.f("ck_representations_erasure"),
        ),
        sa.CheckConstraint(
            "state != 'ACTIVE' OR ann_key IS NOT NULL",
            name=op.f("ck_representations_active_eligible"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACTIVE', 'SUPERSEDED', 'ERASING', 'ERASED', 'DELETED')",
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
        sa.ForeignKeyConstraint(
            ["runtime_variant_id"],
            ["runtime_variants.id"],
            name=op.f("fk_representations_runtime_variant_id_runtime_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_representations")),
        sa.UniqueConstraint(
            "representation_space_id",
            "ann_key",
            name=op.f("uq_representations_representation_space_id_ann_key"),
        ),
        sa.UniqueConstraint(
            "observation_id",
            "representation_space_id",
            name=op.f("uq_representations_observation_id_representation_space_id"),
        ),
        sa.Index(op.f("ix_representations_identity_id_state"), "identity_id", "state"),
        sa.Index(op.f("ix_representations_processing_run_id_state"), "processing_run_id", "state"),
        sa.Index(
            op.f("ix_representations_representation_space_id_state_ann_key"),
            "representation_space_id",
            "state",
            "ann_key",
        ),
    )


def _occurrences() -> sa.Table:
    """`occurrences` as `0001` created it."""
    metadata = _metadata("identities", "observations", "processing_runs", "sources")
    utc = backend.infrastructure.db.types.UTCDateTime
    return sa.Table(
        "occurrences",
        metadata,
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
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("activated_at", utc(), nullable=True),
        sa.CheckConstraint(
            "kind != 'IMAGE' OR (start_frame IS NULL AND end_frame IS NULL"
            " AND start_timestamp_ms IS NULL AND end_timestamp_ms IS NULL)",
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
            "start_timestamp_ms IS NULL OR end_timestamp_ms IS NULL"
            " OR start_timestamp_ms <= end_timestamp_ms",
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
        sa.Index(
            op.f("ix_occurrences_identity_id_state_created_at"),
            "identity_id",
            "state",
            "created_at",
        ),
        sa.Index(op.f("ix_occurrences_processing_run_id_state"), "processing_run_id", "state"),
        sa.Index(
            op.f("ix_occurrences_source_id_state_created_at"), "source_id", "state", "created_at"
        ),
    )


def _evidence(kinds: tuple[str, ...]) -> sa.Table:
    """`evidence` as `0010` left it, with the given kinds."""
    metadata = _metadata(
        "processing_runs", "sources", "identities", "people", "recognition_calibration_profiles"
    )
    utc = backend.infrastructure.db.types.UTCDateTime
    table = sa.Table(
        "evidence",
        metadata,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid()),
        sa.Column("source_id", sa.Uuid()),
        sa.Column("subject_identity_id", sa.Uuid()),
        sa.Column("subject_person_id", sa.Uuid()),
        sa.Column("calibration_profile_id", sa.Uuid()),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("superseded_at", utc()),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(repr(kind) for kind in kinds) + ")",
            name=op.f("ck_evidence_kind"),
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
        sa.ForeignKeyConstraint(
            ["calibration_profile_id"],
            ["recognition_calibration_profiles.id"],
            name=op.f("fk_evidence_calibration_profile_id_recognition_calibration_profiles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    sa.Index(op.f("ix_evidence_kind_created_at"), table.c.kind, table.c.created_at)
    sa.Index(
        op.f("ix_evidence_processing_run_id_created_at"),
        table.c.processing_run_id,
        table.c.created_at,
    )
    sa.Index(
        op.f("ix_evidence_subject_identity_id_created_at"),
        table.c.subject_identity_id,
        table.c.created_at,
    )
    return table


def _superseded_at() -> sa.Column[object]:
    return sa.Column("superseded_at", backend.infrastructure.db.types.UTCDateTime(), nullable=True)


def upgrade() -> None:
    op.execute(f"DROP TRIGGER {SNAPSHOT_TRIGGER}")
    with op.batch_alter_table(
        "processing_runs", copy_from=_processing_runs(), recreate="always"
    ) as batch_op:
        batch_op.add_column(sa.Column("supersedes_run_id", sa.Uuid(), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_processing_runs_supersedes_not_self"), SUPERSEDES_NOT_SELF
        )
        batch_op.create_foreign_key(
            op.f(SUPERSEDES_FK),
            "processing_runs",
            ["supersedes_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            ONE_COMPLETED_SUPERSEDER,
            ["supersedes_run_id"],
            unique=True,
            sqlite_where=sa.text("state = 'COMPLETED'"),
        )
    op.execute(SNAPSHOT_TRIGGER_SQL)
    for table, check in (
        (_observations(), OBSERVATION_SUPERSEDED),
        (_representations(), SUPERSEDED_HAS_TIME),
        (_occurrences(), SUPERSEDED_HAS_TIME),
    ):
        with op.batch_alter_table(table.name, copy_from=table, recreate="always") as batch_op:
            batch_op.add_column(_superseded_at())
            batch_op.create_check_constraint(op.f(f"ck_{table.name}_superseded_has_time"), check)
    with op.batch_alter_table("evidence", copy_from=_evidence(KINDS_AFTER), recreate="always"):
        pass


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    # Each earlier shape is a subset of the current one: the copy keeps every earlier column and
    # drops the ones this revision added (and the older `evidence.kind` CHECK refuses the copy, so
    # the whole downgrade, while a reprocessing Evidence row exists).
    with op.batch_alter_table("evidence", copy_from=_evidence(KINDS_BEFORE), recreate="always"):
        pass
    for table in (_occurrences(), _representations(), _observations()):
        with op.batch_alter_table(table.name, copy_from=table, recreate="always"):
            pass
    op.execute(f"DROP TRIGGER {SNAPSHOT_TRIGGER}")
    with op.batch_alter_table("processing_runs", copy_from=_processing_runs(), recreate="always"):
        pass
    op.execute(SNAPSHOT_TRIGGER_SQL)
