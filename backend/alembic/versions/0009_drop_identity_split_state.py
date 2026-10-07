"""remove the never-assigned `SPLIT` identity state

Owner decision 2026-10-07 (CONTEXT question 15): a split is recorded by `IDENTITY_SPLIT` Evidence and
lineage, never by an identity state, so `SPLIT` leaves the allowed states. A database that holds an
identity in that state (nothing ever wrote one) is refused by the new check, and nothing changes.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AFTER = ("PENDING", "ACTIVE", "MERGED", "FORGOTTEN", "DELETED")
BEFORE = ("PENDING", "ACTIVE", "MERGED", "SPLIT", "FORGOTTEN", "DELETED")


def _identities(states: tuple[str, ...]) -> sa.Table:
    metadata = sa.MetaData()
    for name in ("processing_runs", "observations"):
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    utc = backend.infrastructure.db.types.UTCDateTime
    return sa.Table(
        "identities",
        metadata,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_by_processing_run_id", sa.Uuid()),
        sa.Column("representative_observation_id", sa.Uuid()),
        sa.Column("merged_into_identity_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("activated_at", utc()),
        sa.Column("forgotten_at", utc()),
        sa.Column("updated_at", utc(), nullable=False),
        sa.CheckConstraint(
            "state != 'MERGED' OR merged_into_identity_id IS NOT NULL",
            name=op.f("ck_identities_merged_target"),
        ),
        sa.CheckConstraint(
            "state IN (" + ", ".join(repr(state) for state in states) + ")",
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


def _recreate(states: tuple[str, ...]) -> None:
    with op.batch_alter_table("identities", recreate="always", copy_from=_identities(states)):
        pass


def upgrade() -> None:
    _recreate(AFTER)


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    _recreate(BEFORE)
