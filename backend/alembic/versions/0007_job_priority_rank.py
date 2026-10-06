"""give jobs an integer priority rank for claim ordering

`jobs.priority` is a descriptive string, and ordering by it is alphabetical (HIGH before
INTERACTIVE), so the scheduler cannot claim INTERACTIVE work first from it (CONTEXT question 14).
Owner decision 2026-10-06: an integer `priority_rank` column, added before the scheduler loop; the
string is never scheduling semantics. A CHECK keeps the two in agreement, and the claim index is
`(state, priority_rank, created_at)`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Most urgent first. Written out here, not imported: a revision describes the schema as it was.
PRIORITIES = ("INTERACTIVE", "HIGH", "NORMAL", "LOW", "MAINTENANCE")
# An unknown priority is left to `ck_jobs_priority`, so that is the constraint a bad row names.
RANK_CHECK = (
    "priority_rank = CASE priority "
    + " ".join(f"WHEN '{name}' THEN {rank}" for rank, name in enumerate(PRIORITIES))
    + " ELSE priority_rank END"
)
BACKFILL = (
    "UPDATE jobs SET priority_rank = CASE priority "
    + " ".join(f"WHEN '{name}' THEN {rank}" for rank, name in enumerate(PRIORITIES))
    + " END"
)


def _jobs(*, ranked: bool) -> sa.Table:
    metadata = sa.MetaData()
    sa.Table("processing_runs", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    utc = backend.infrastructure.db.types.UTCDateTime
    columns: list[sa.Column[Any]] = [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("previous_job_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
    ]
    if ranked:
        columns.append(sa.Column("priority_rank", sa.Integer(), nullable=False))
    columns += [
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
    ]
    constraints: list[sa.schema.SchemaItem] = [
        sa.CheckConstraint(
            "priority IN ('INTERACTIVE', 'HIGH', 'NORMAL', 'LOW', 'MAINTENANCE')",
            name=op.f("ck_jobs_priority"),
        ),
        sa.CheckConstraint(
            "progress_mode IN ('DETERMINATE', 'INDETERMINATE')", name=op.f("ck_jobs_progress_mode")
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'CANCELLED',"
            " 'COMPLETED', 'FAILED', 'INTERRUPTED')",
            name=op.f("ck_jobs_state"),
        ),
        sa.CheckConstraint(
            "type IN ('PROCESS_SOURCE', 'REPROCESS_SOURCE', 'REBUILD_INDEX', 'RETRAIN_MODEL',"
            " 'INSTALL_RUNTIME', 'CLEAN_STORAGE')",
            name=op.f("ck_jobs_type"),
        ),
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
    ]
    if ranked:
        constraints.append(
            sa.CheckConstraint(RANK_CHECK, name=op.f("ck_jobs_priority_rank_matches_priority"))
        )
    constraints += [
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
    ]
    table = sa.Table("jobs", metadata, *columns, *constraints)
    sa.Index(op.f("ix_jobs_lease_expires_at"), table.c.lease_expires_at)
    sa.Index(op.f("ix_jobs_processing_run_id"), table.c.processing_run_id)
    if ranked:
        sa.Index(
            op.f("ix_jobs_state_priority_rank_created_at"),
            table.c.state,
            table.c.priority_rank,
            table.c.created_at,
        )
    else:
        sa.Index(
            op.f("ix_jobs_state_priority_created_at"),
            table.c.state,
            table.c.priority,
            table.c.created_at,
        )
    return table


def upgrade() -> None:
    # SQLite can add a column with a constant default natively; fill it from the string, then
    # recreate the table so the default goes and the CHECK and the new claim index arrive.
    op.execute("ALTER TABLE jobs ADD COLUMN priority_rank INTEGER NOT NULL DEFAULT 2")
    op.execute(BACKFILL)
    with op.batch_alter_table("jobs", recreate="always", copy_from=_jobs(ranked=True)):
        pass


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    with op.batch_alter_table("jobs", recreate="always", copy_from=_jobs(ranked=False)):
        pass
