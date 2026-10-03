"""accepted ABSTAIN representations, output provenance, snapshots that cannot be replaced

Three decisions (PERSISTENCE_IMPLEMENTATION.md §5, §6.2, §13; GitHub issues 55 and 88; CONTEXT open
questions 31 and the M3 plan):

1. An accepted `ABSTAIN` representation is `ACTIVE` with no identity (decision 2026-10-02), so the
   `active_eligible` CHECK relaxes from `state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS
   NOT NULL)` to `state != 'ACTIVE' OR ann_key IS NOT NULL`. Only the identity half goes: an `ACTIVE`
   row without an `ann_key` stays refused, and whether an identity-less row is a legitimate
   abstention is the acceptance use case's rule.
2. Output-level execution provenance (decision 2026-10-03, issue 88): a nullable
   `runtime_variant_id` foreign key (`RESTRICT`) on `representations` (the embedder variant that
   executed) and on `observations` (the detector variant that executed). Existing rows keep NULL.
3. A third snapshot trigger blocks `INSERT OR REPLACE` (issue 55): SQLite fires no delete trigger for
   the deletion REPLACE performs, so a snapshot no run uses could be rewritten. The trigger fires
   before the conflict is resolved.

SQLite cannot alter a CHECK or add a named foreign key in place, so `representations` and
`observations` are recreated (batch mode, from frozen definitions: see revision 0002). Every row is
kept; the new CHECK is weaker than the old one and the new columns are NULL, so no existing database
can violate them. The trigger text is a copy of `SNAPSHOT_NO_REPLACE_TRIGGER` in
`backend/app/processing/models.py` and must stay byte-identical to it.

Downgrade restores the stricter CHECK, drops the two columns and the trigger. It is refused by the
downgrade guard while the library holds data (and, with the override, atomically while an
identity-less `ACTIVE` row exists: the older schema cannot hold it).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NO_REPLACE_TRIGGER = (
    "CREATE TRIGGER trg_processing_configuration_snapshots_no_replace "
    "BEFORE INSERT ON processing_configuration_snapshots "
    "WHEN EXISTS (SELECT 1 FROM processing_configuration_snapshots WHERE id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'a processing configuration snapshot is immutable and cannot be "
    "replaced'); END"
)

STATES = ("PENDING", "ACTIVE", "SUPERSEDED", "ERASING", "ERASED", "DELETED")
ACTIVE_ELIGIBLE_BEFORE = "state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)"
ACTIVE_ELIGIBLE_AFTER = "state != 'ACTIVE' OR ann_key IS NOT NULL"
REPRESENTATION_VARIANT_FK = "fk_representations_runtime_variant_id_runtime_variants"
OBSERVATION_VARIANT_FK = "fk_observations_runtime_variant_id_runtime_variants"


def _stubs(metadata: sa.MetaData, *names: str) -> None:
    for referenced in names:  # a foreign key needs its target table in the same MetaData
        sa.Table(referenced, metadata, sa.Column("id", sa.Uuid(), primary_key=True))


def _representations(*, upgraded: bool) -> sa.Table:
    """`representations` as `0003` left it, or (`upgraded`) as this revision leaves it."""
    metadata = sa.MetaData()
    _stubs(
        metadata,
        "execution_segments",
        "identities",
        "observations",
        "processing_runs",
        "representation_spaces",
        "runtime_variants",
    )
    utc = backend.infrastructure.db.types.UTCDateTime
    states = ", ".join(f"'{state}'" for state in STATES)
    eligible = ACTIVE_ELIGIBLE_AFTER if upgraded else ACTIVE_ELIGIBLE_BEFORE
    columns: list[sa.schema.SchemaItem] = [
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
    ]
    if upgraded:
        columns.append(sa.Column("runtime_variant_id", sa.Uuid(), nullable=True))
    constraints: list[sa.schema.SchemaItem] = [
        sa.CheckConstraint(
            "(state = 'ERASED' AND vector IS NULL AND ann_key IS NULL) OR (state != 'ERASED' AND vector IS NOT NULL)",
            name=op.f("ck_representations_erasure"),
        ),
        sa.CheckConstraint(eligible, name=op.f("ck_representations_active_eligible")),
        sa.CheckConstraint(f"state IN ({states})", name=op.f("ck_representations_state")),
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
    ]
    if upgraded:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["runtime_variant_id"],
                ["runtime_variants.id"],
                name=op.f(REPRESENTATION_VARIANT_FK),
                ondelete="RESTRICT",
            )
        )
    return sa.Table(
        "representations",
        metadata,
        *columns,
        *constraints,
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


def _observations(*, upgraded: bool) -> sa.Table:
    """`observations` as `0001` created it, or (`upgraded`) with the provenance column."""
    metadata = sa.MetaData()
    _stubs(
        metadata,
        "artifacts",
        "component_versions",
        "execution_segments",
        "processing_runs",
        "runtime_variants",
        "sources",
    )
    utc = backend.infrastructure.db.types.UTCDateTime
    columns: list[sa.schema.SchemaItem] = [
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
    ]
    if upgraded:
        columns.append(sa.Column("runtime_variant_id", sa.Uuid(), nullable=True))
    constraints: list[sa.schema.SchemaItem] = [
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
    ]
    if upgraded:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["runtime_variant_id"],
                ["runtime_variants.id"],
                name=op.f(OBSERVATION_VARIANT_FK),
                ondelete="RESTRICT",
            )
        )
    return sa.Table(
        "observations",
        metadata,
        *columns,
        *constraints,
        sa.PrimaryKeyConstraint("id", name=op.f("pk_observations")),
        sa.UniqueConstraint(
            "processing_run_id",
            "sequence_in_run",
            name=op.f("uq_observations_processing_run_id_sequence_in_run"),
        ),
        sa.Index(op.f("ix_observations_face_crop_artifact_id"), "face_crop_artifact_id"),
        sa.Index(
            op.f("ix_observations_source_id_state_created_at"),
            "source_id",
            "state",
            "created_at",
        ),
    )


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(
        "representations",
        schema=None,
        copy_from=_representations(upgraded=False),
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(op.f("ck_representations_active_eligible"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_representations_active_eligible"), ACTIVE_ELIGIBLE_AFTER
        )
        batch_op.add_column(sa.Column("runtime_variant_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            op.f(REPRESENTATION_VARIANT_FK),
            "runtime_variants",
            ["runtime_variant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table(
        "observations", schema=None, copy_from=_observations(upgraded=False), recreate="always"
    ) as batch_op:
        batch_op.add_column(sa.Column("runtime_variant_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            op.f(OBSERVATION_VARIANT_FK),
            "runtime_variants",
            ["runtime_variant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(NO_REPLACE_TRIGGER)


def downgrade() -> None:
    """Downgrade schema. Refused (atomically) while an identity-less `ACTIVE` representation
    exists: the older schema cannot hold it."""
    require_destructive_downgrade_allowed(op.get_bind())
    op.execute("DROP TRIGGER trg_processing_configuration_snapshots_no_replace")
    with op.batch_alter_table(
        "observations", schema=None, copy_from=_observations(upgraded=True), recreate="always"
    ) as batch_op:
        batch_op.drop_constraint(op.f(OBSERVATION_VARIANT_FK), type_="foreignkey")
        batch_op.drop_column("runtime_variant_id")
    with op.batch_alter_table(
        "representations",
        schema=None,
        copy_from=_representations(upgraded=True),
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(op.f(REPRESENTATION_VARIANT_FK), type_="foreignkey")
        batch_op.drop_column("runtime_variant_id")
        batch_op.drop_constraint(op.f("ck_representations_active_eligible"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_representations_active_eligible"), ACTIVE_ELIGIBLE_BEFORE
        )
