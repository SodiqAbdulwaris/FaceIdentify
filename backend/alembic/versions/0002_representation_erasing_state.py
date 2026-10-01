"""add the ERASING representation state

Erasure is two-step (PERSISTENCE_IMPLEMENTATION.md §6.2, decision 2026-10-01, CONTEXT open question
25): the representation moves ACTIVE -> ERASING while its REMOVE is queued, and only becomes ERASED
once the index no longer holds the vector. `ERASING` keeps its vector and ann_key, so the `erasure`
and `active_eligible` CHECKs are unchanged; only the `state` CHECK lists a new value.

SQLite cannot alter a CHECK constraint in place, so `representations` is recreated (batch mode).
The table is passed to Alembic as a frozen definition (`copy_from`) rather than reflected, for two
reasons: `upgrade --sql` can then print the SQL without a live database, and the revision does not
depend on how SQLAlchemy happens to reflect CHECK constraints. The frozen definitions are the
`0001` table with only the `state` CHECK differing; they must keep matching `0001` and the model
(`test_migrations.py` compares the migrated schema with `create_all`).

Recreating a table other tables reference needs foreign key enforcement off while it is dropped:
`env.py` does that outside the transaction and checks `PRAGMA foreign_key_check` before commit.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES_BEFORE = ("PENDING", "ACTIVE", "SUPERSEDED", "ERASED", "DELETED")
STATES_AFTER = ("PENDING", "ACTIVE", "SUPERSEDED", "ERASING", "ERASED", "DELETED")


def _state_check(states: Sequence[str]) -> str:
    return "state IN (" + ", ".join(f"'{state}'" for state in states) + ")"


def _representations(states: Sequence[str]) -> sa.Table:
    """`representations` as `0001` created it, with `states` in its `state` CHECK."""
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
        sa.CheckConstraint(_state_check(states), name=op.f("ck_representations_state")),
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
        sa.Index(op.f("ix_representations_identity_id_state"), "identity_id", "state"),
        sa.Index(op.f("ix_representations_processing_run_id_state"), "processing_run_id", "state"),
        sa.Index(
            op.f("ix_representations_representation_space_id_state_ann_key"),
            "representation_space_id",
            "state",
            "ann_key",
        ),
    )


def _replace_state_check(*, old: Sequence[str], new: Sequence[str]) -> None:
    with op.batch_alter_table(
        "representations", schema=None, copy_from=_representations(old), recreate="always"
    ) as batch_op:
        batch_op.drop_constraint(op.f("ck_representations_state"), type_="check")
        batch_op.create_check_constraint(op.f("ck_representations_state"), _state_check(new))


def upgrade() -> None:
    """Upgrade schema."""
    _replace_state_check(old=STATES_BEFORE, new=STATES_AFTER)


def downgrade() -> None:
    """Downgrade schema. Refused by the database (atomically) while any representation is still
    ERASING: that state cannot be expressed in the older schema."""
    _replace_state_check(old=STATES_AFTER, new=STATES_BEFORE)
