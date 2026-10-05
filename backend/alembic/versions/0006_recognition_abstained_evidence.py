"""add the immutable accepted-abstention Evidence kind

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = (
    "IDENTITY_CREATED",
    "IDENTITY_MATCHED",
    "IDENTITY_ASSIGNED_TO_PERSON",
    "IDENTITY_REMOVED_FROM_PERSON",
    "IDENTITY_MERGED",
    "IDENTITY_SPLIT",
    "IDENTITY_FORGOTTEN",
    "USER_CORRECTION",
)
AFTER = BEFORE[:2] + ("RECOGNITION_ABSTAINED",) + BEFORE[2:]


def _evidence(kinds: tuple[str, ...]) -> sa.Table:
    metadata = sa.MetaData()
    for name in (
        "processing_runs",
        "sources",
        "identities",
        "people",
        "recognition_calibration_profiles",
    ):
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
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


def _recreate(kinds: tuple[str, ...]) -> None:
    with op.batch_alter_table("evidence", recreate="always", copy_from=_evidence(kinds)):
        pass


def upgrade() -> None:
    _recreate(AFTER)


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    _recreate(BEFORE)
