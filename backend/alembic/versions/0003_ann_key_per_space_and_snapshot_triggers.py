"""ann_key unique per space; immutable processing configuration snapshots

Two decisions of 2026-10-01 (PERSISTENCE_IMPLEMENTATION.md §6.2/§6.3 and §13; GitHub issues 48 and 51):

1. `representations.ann_key` was unique across the whole table, while `ann_key_sequences` allocates a
   sequence per space that each starts at 1, so two spaces collided. It is now
   `UNIQUE(representation_space_id, ann_key)`. SQLite cannot drop a table-level UNIQUE in place, so
   `representations` is recreated (batch mode, from a frozen definition: see revision 0002). Every row and
   key is kept; the new constraint is weaker than the old one, so no existing database can violate it.
2. Two triggers make a committed `processing_configuration_snapshots` row immutable: `UPDATE` always aborts,
   and `DELETE` aborts while a run references the snapshot. (One snapshot per run is already
   `uq_processing_runs_configuration_snapshot_id`, from revision 0001.)

The trigger texts are copies of `SNAPSHOT_NO_UPDATE_TRIGGER` and `SNAPSHOT_NO_DELETE_WHILE_USED_TRIGGER` in
`backend/app/processing/models.py` and must stay byte-identical to them: the migration tests compare the
migrated schema with `create_all`.

Downgrade restores the table-wide constraint and drops the triggers. It is refused, atomically, while two
spaces hold the same key (the old schema cannot).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NO_UPDATE_TRIGGER = (
    "CREATE TRIGGER trg_processing_configuration_snapshots_no_update "
    "BEFORE UPDATE ON processing_configuration_snapshots "
    "BEGIN SELECT RAISE(ABORT, 'a processing configuration snapshot is immutable'); END"
)
NO_DELETE_WHILE_USED_TRIGGER = (
    "CREATE TRIGGER trg_processing_configuration_snapshots_no_delete_while_used "
    "BEFORE DELETE ON processing_configuration_snapshots "
    "WHEN EXISTS (SELECT 1 FROM processing_runs WHERE configuration_snapshot_id = OLD.id) "
    "BEGIN SELECT RAISE(ABORT, 'a processing configuration snapshot that a run uses cannot be "
    "deleted'); END"
)

STATES = ("PENDING", "ACTIVE", "SUPERSEDED", "ERASING", "ERASED", "DELETED")


def _representations(*, ann_key_unique_per_space: bool) -> sa.Table:
    """`representations` as `0002` left it, with the ann_key uniqueness of the given direction."""
    metadata = sa.MetaData()
    for referenced in (
        "execution_segments",
        "identities",
        "observations",
        "processing_runs",
        "representation_spaces",
    ):  # stubs: a foreign key needs its target table in the same MetaData to be rendered
        sa.Table(referenced, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    utc = backend.infrastructure.db.types.UTCDateTime
    states = ", ".join(f"'{state}'" for state in STATES)
    ann_key_unique = (
        sa.UniqueConstraint(
            "representation_space_id",
            "ann_key",
            name=op.f("uq_representations_representation_space_id_ann_key"),
        )
        if ann_key_unique_per_space
        else sa.UniqueConstraint("ann_key", name=op.f("uq_representations_ann_key"))
    )
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
        sa.CheckConstraint(
            "(state = 'ERASED' AND vector IS NULL AND ann_key IS NULL) OR (state != 'ERASED' AND vector IS NOT NULL)",
            name=op.f("ck_representations_erasure"),
        ),
        sa.CheckConstraint(
            "state != 'ACTIVE' OR (identity_id IS NOT NULL AND ann_key IS NOT NULL)",
            name=op.f("ck_representations_active_eligible"),
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_representations")),
        ann_key_unique,
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


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(
        "representations",
        schema=None,
        copy_from=_representations(ann_key_unique_per_space=False),
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(op.f("uq_representations_ann_key"), type_="unique")
        batch_op.create_unique_constraint(
            op.f("uq_representations_representation_space_id_ann_key"),
            ["representation_space_id", "ann_key"],
        )
    op.execute(NO_UPDATE_TRIGGER)
    op.execute(NO_DELETE_WHILE_USED_TRIGGER)


def downgrade() -> None:
    """Downgrade schema. Refused by the database (atomically) while two spaces hold the same
    ann_key: the older schema cannot."""
    op.execute("DROP TRIGGER trg_processing_configuration_snapshots_no_delete_while_used")
    op.execute("DROP TRIGGER trg_processing_configuration_snapshots_no_update")
    with op.batch_alter_table(
        "representations",
        schema=None,
        copy_from=_representations(ann_key_unique_per_space=True),
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(
            op.f("uq_representations_representation_space_id_ann_key"), type_="unique"
        )
        batch_op.create_unique_constraint(op.f("uq_representations_ann_key"), ["ann_key"])
