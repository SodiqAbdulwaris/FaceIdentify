"""add the app_state key/value table (the durable "WAL truncation owed" marker)

Decision 2026-10-01 (owner; GitHub issue 52, PERSISTENCE_IMPLEMENTATION.md §25): an erasure commits
`ERASED` before the write-ahead log is truncated, so the database must be able to say that the
truncation is still owed after a crash between the two. The marker is a row of this table,
`wal_truncation_owed`, written in the transaction that clears the vector and key and deleted only after
a truncating checkpoint has succeeded. A generic key/value table keeps later "owed" facts from needing
a revision each. The table is new, so nothing is recreated.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", backend.infrastructure.db.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint("key != ''", name=op.f("ck_app_state_key_not_empty")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_state")),
    )


def downgrade() -> None:
    """Downgrade schema. Drops the markers with the table: a pending truncation is then forgotten,
    which is why a downgrade is a development operation only."""
    op.drop_table("app_state")
