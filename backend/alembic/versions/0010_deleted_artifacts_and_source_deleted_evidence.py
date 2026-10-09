"""a deleted artifact may have no location; add the source-deleted Evidence kind

Owner decision 2026-10-09 (M5 step 4c): permanently deleting a Source that referenced a user's file
must leave no recoverable path behind, so an artifact in the `DELETED` state is exempt from the
`location` check (a referenced one then carries no `external_path`), and a non-biometric
`SOURCE_PERMANENTLY_DELETED` historical entry joins the Evidence kinds (identity model section 41).

Existing rows satisfy the looser check and the longer list, so nothing is rejected. One thing does
change: a referenced original that an earlier revision already deleted (or began to delete) still
carries its path, which this revision exists to remove, so the upgrade clears it and the
file-describing columns with it, and records that the write-ahead log is owed a truncation (its older
pages hold those values), which startup recovery settles. A downgrade restores
the stricter checks and is refused by them if a library already holds a deleted artifact without a
location or a `SOURCE_PERMANENTLY_DELETED` entry.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import context, op

import backend.infrastructure.db.types
from backend.infrastructure.db.downgrade_guard import require_destructive_downgrade_allowed

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
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
)
KINDS_AFTER = (*KINDS_BEFORE, "SOURCE_PERMANENTLY_DELETED")

LOCATION_BEFORE = (
    "(storage_mode = 'MANAGED' AND storage_key IS NOT NULL AND external_path IS NULL)"
    " OR (storage_mode = 'REFERENCED' AND external_path IS NOT NULL AND storage_key IS NULL)"
)
LOCATION_AFTER = LOCATION_BEFORE + " OR state = 'DELETED'"


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


def _artifacts(location: str) -> sa.Table:
    metadata = sa.MetaData()
    utc = backend.infrastructure.db.types.UTCDateTime
    table = sa.Table(
        "artifacts",
        metadata,
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
        sa.Column("created_at", utc(), nullable=False),
        sa.Column("available_at", utc(), nullable=True),
        sa.Column("delete_requested_at", utc(), nullable=True),
        sa.Column("deleted_at", utc(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_detail", sa.String(), nullable=True),
        sa.CheckConstraint(location, name=op.f("ck_artifacts_location")),
        sa.CheckConstraint(
            "NOT (state = 'AVAILABLE' AND storage_mode = 'MANAGED'"
            " AND (sha256 IS NULL OR size_bytes IS NULL))",
            name=op.f("ck_artifacts_available_managed_verified"),
        ),
        sa.CheckConstraint(
            "kind IN ('SOURCE_ORIGINAL', 'FACE_CROP', 'THUMBNAIL', 'MODEL_EXPORT',"
            " 'RUNTIME_PACKAGE')",
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
    sa.Index(op.f("ix_artifacts_sha256"), table.c.sha256)
    sa.Index(op.f("ix_artifacts_state_created_at"), table.c.state, table.c.created_at)
    return table


def _recreate(kinds: tuple[str, ...], location: str) -> None:
    with op.batch_alter_table("evidence", recreate="always", copy_from=_evidence(kinds)):
        pass
    with op.batch_alter_table("artifacts", recreate="always", copy_from=_artifacts(location)):
        pass


def upgrade() -> None:
    _recreate(KINDS_AFTER, LOCATION_AFTER)
    clear = sa.text(
        "UPDATE artifacts SET external_path = NULL, original_filename = NULL, mime_type = NULL,"
        " sha256 = NULL, size_bytes = NULL"
        " WHERE storage_mode = 'REFERENCED' AND state = 'DELETED'"
        " AND (external_path IS NOT NULL OR original_filename IS NOT NULL OR sha256 IS NOT NULL)"
    )
    if context.is_offline_mode():  # a printed script has no database to ask how many rows changed
        op.execute(clear)
        return
    cleared = op.get_bind().execute(clear).rowcount
    if cleared:  # the log still holds the old values: owe a truncation (startup settles it)
        op.get_bind().execute(
            sa.text(
                "INSERT INTO app_state (key, value, updated_at) VALUES"
                " ('wal_truncation_owed', :value, :now)"
                " ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = :now"
            ),
            {"value": uuid.uuid4().hex, "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")},
        )


def downgrade() -> None:
    require_destructive_downgrade_allowed(op.get_bind())
    _recreate(KINDS_BEFORE, LOCATION_BEFORE)
