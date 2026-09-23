"""Constraint tests for the provenance, runtime-catalog and settings models (M1 PR 1).

Each test starts from a valid row and breaks exactly one rule, so a failure points at one
constraint. The local builders are replaced by tests/factories/ in M1 PR 3.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from backend.app.jobs.models import Job
from backend.app.memory.models import RepresentationSpace
from backend.app.models import Base
from backend.app.processing.models import (
    ExecutionSegment,
    ProcessingCheckpoint,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)
from backend.app.runtime.models import Component, ComponentVersion
from backend.app.settings.models import ProcessingSettings
from backend.app.sources.models import Artifact, Source
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

SHA = hashlib.sha256(b"bytes").digest()


def check(name: str) -> str:
    """Regex for exactly this CHECK constraint failing (not one whose name merely starts so)."""
    return re.escape(name) + r"(\n|$)"


def unique(*columns: str) -> str:
    """Regex for exactly this UNIQUE column set failing, in SQLite's message format."""
    return "UNIQUE constraint failed: " + re.escape(", ".join(columns)) + r"(\n|$)"


class Builder:
    """Valid rows with overridable fields, all ids and times deterministic."""

    def __init__(self, session: Session, clock: FrozenClock, new_id: SeededUUIDs) -> None:
        self.session, self.clock, self.new_id = session, clock, new_id

    def add[T](self, row: T) -> T:
        self.session.add(row)
        self.session.flush()
        return row

    def artifact(self, **kw: Any) -> Artifact:
        fields: dict[str, Any] = dict(
            id=self.new_id(), kind="SOURCE_ORIGINAL", storage_mode="MANAGED", state="AVAILABLE",
            storage_key=f"originals/{self.new_id()}", sha256=SHA, size_bytes=5,
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(Artifact(**(fields | kw)))

    def source(self, **kw: Any) -> Source:
        fields: dict[str, Any] = dict(
            id=self.new_id(), kind="IMAGE", state="ACTIVE", display_name="beach.jpg",
            original_artifact_id=kw.pop("original_artifact_id", None) or self.artifact().id,
            created_at=self.clock(), updated_at=self.clock(),
        )  # fmt: skip
        return self.add(Source(**(fields | kw)))

    def snapshot(self) -> ProcessingConfigurationSnapshot:
        return self.add(
            ProcessingConfigurationSnapshot(
                id=self.new_id(), schema_version=1, canonical_json={}, fingerprint_sha256=SHA,
                created_at=self.clock(),
            )
        )  # fmt: skip

    def run(self, **kw: Any) -> ProcessingRun:
        fields: dict[str, Any] = dict(
            id=self.new_id(), source_id=kw.pop("source_id", None) or self.source().id,
            configuration_snapshot_id=kw.pop("configuration_snapshot_id", None)
            or self.snapshot().id,
            state="RUNNING", requested_at=self.clock(), created_at=self.clock(),
            updated_at=self.clock(),
        )  # fmt: skip
        return self.add(ProcessingRun(**(fields | kw)))

    def segment(self, run: ProcessingRun, ordinal: int, state: str) -> ExecutionSegment:
        return self.add(
            ExecutionSegment(
                id=self.new_id(), processing_run_id=run.id, ordinal=ordinal, state=state,
                runtime_details_json={}, started_at=self.clock(), created_at=self.clock(),
            )
        )  # fmt: skip

    def checkpoint(
        self, run: ProcessingRun, ordinal: int, kind: str, state: str
    ) -> ProcessingCheckpoint:
        return self.add(
            ProcessingCheckpoint(
                id=self.new_id(), processing_run_id=run.id, ordinal=ordinal, kind=kind,
                state=state, payload_schema_version=1, payload_json={}, created_at=self.clock(),
            )
        )  # fmt: skip

    def job(self, **kw: Any) -> Job:
        fields: dict[str, Any] = dict(
            id=self.new_id(), type="PROCESS_SOURCE", state="QUEUED", priority="NORMAL",
            payload_schema_version=1, progress_mode="DETERMINATE", created_at=self.clock(),
            updated_at=self.clock(),
        )  # fmt: skip
        return self.add(Job(**(fields | kw)))

    def representation_space(self, **kw: Any) -> RepresentationSpace:
        component = self.add(
            Component(
                id=self.new_id(), key=f"detector-{self.new_id()}", kind="FACE_REPRESENTATION",
                display_name="Embedder", state="ACTIVE",
            )
        )  # fmt: skip
        version = self.add(
            ComponentVersion(
                id=self.new_id(), component_id=component.id, semantic_version="1.0.0",
                contract_schema_version=1, contract_json={}, created_at=self.clock(),
            )
        )  # fmt: skip
        fields: dict[str, Any] = dict(
            id=self.new_id(), semantic_key=f"space-{self.new_id()}", state="ACTIVE",
            dimension=512, metric="COSINE", normalization="L2_NORMALIZED",
            component_version_id=version.id, contract_schema_version=1, contract_json={},
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(RepresentationSpace(**(fields | kw)))


@pytest.fixture
def build(db_session: Session, clock: FrozenClock, new_id: SeededUUIDs) -> Builder:
    return Builder(db_session, clock, new_id)


def rejected(build: Builder, make: Any, constraint: str) -> None:
    """Assert that building a row violates the named constraint, then reset the session."""
    with pytest.raises(IntegrityError, match=constraint):
        make()
    build.session.rollback()


# --- conventions -----------------------------------------------------------------------------


def test_every_constraint_is_named_for_alembic_batch_mode() -> None:
    unnamed = [
        f"{table.name}: {type(c).__name__}"
        for table in Base.metadata.tables.values()
        for c in table.constraints
        if isinstance(c, CheckConstraint | UniqueConstraint | ForeignKeyConstraint) and not c.name
    ]
    assert unnamed == []


def test_utc_datetime_round_trips_and_normalises_offsets(build: Builder) -> None:
    lagos = timezone(timedelta(hours=1))
    local = datetime(2026, 3, 1, 13, 30, tzinfo=lagos)
    artifact = build.artifact(created_at=local)
    build.session.expire_all()
    loaded = build.session.get(Artifact, artifact.id)
    assert loaded is not None
    assert loaded.created_at == datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
    assert loaded.created_at.tzinfo is UTC


def test_utc_datetime_rejects_naive_values(build: Builder) -> None:
    with pytest.raises(StatementError, match="timezone-aware"):
        build.artifact(created_at=datetime(2026, 3, 1, 12, 30))


def test_primary_keys_are_uuid4_by_default(db_session: Session, clock: FrozenClock) -> None:
    snapshot = ProcessingConfigurationSnapshot(
        schema_version=1, canonical_json={}, fingerprint_sha256=SHA, created_at=clock()
    )
    db_session.add(snapshot)
    db_session.flush()
    assert isinstance(snapshot.id, uuid.UUID)
    assert snapshot.id.version == 4


# --- artifacts and sources -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "column"),
    [
        ("artifact", "kind"),
        ("artifact", "storage_mode"),
        ("artifact", "state"),
        ("source", "kind"),
        ("source", "state"),
        ("run", "state"),
        ("job", "type"),
        ("job", "state"),
        ("job", "priority"),
        ("job", "progress_mode"),
        ("representation_space", "state"),
        ("representation_space", "metric"),
    ],
)
def test_spec_defined_value_sets_reject_unknown_literals(
    build: Builder, row: str, column: str
) -> None:
    table = {"artifact": "artifacts", "source": "sources", "run": "processing_runs",
             "job": "jobs", "representation_space": "representation_spaces"}[row]  # fmt: skip
    make = getattr(build, row)
    rejected(build, lambda: make(**{column: "NOT_A_VALUE"}), check(f"ck_{table}_{column}"))


def test_segment_and_checkpoint_value_sets(build: Builder) -> None:
    run = build.run()
    rejected(build, lambda: build.segment(run, 0, "PAUSED"), check("ck_execution_segments_state"))
    run = build.run()
    rejected(
        build,
        lambda: build.checkpoint(run, 0, "PARTIAL", "VALID"),
        check("ck_processing_checkpoints_kind"),
    )
    run = build.run()
    rejected(
        build,
        lambda: build.checkpoint(run, 0, "FINAL", "STALE"),
        check("ck_processing_checkpoints_state"),
    )


def test_segment_end_reason_is_optional_but_constrained(build: Builder) -> None:
    run = build.run()
    segment = build.segment(run, 0, "RUNNING")
    assert segment.ended_reason is None
    segment.state, segment.ended_reason = "COMPLETED", "NORMAL"
    build.session.flush()
    segment.ended_reason = "BORED"
    rejected(build, build.session.flush, check("ck_execution_segments_ended_reason"))


def test_managed_artifact_requires_storage_key_and_no_external_path(build: Builder) -> None:
    rejected(build, lambda: build.artifact(storage_key=None), check("ck_artifacts_location"))
    rejected(
        build,
        lambda: build.artifact(external_path="C:/photos/a.jpg"),
        check("ck_artifacts_location"),
    )


def test_referenced_artifact_requires_external_path_and_no_storage_key(build: Builder) -> None:
    referenced = build.artifact(
        storage_mode="REFERENCED", storage_key=None, external_path="C:/photos/a.jpg"
    )
    assert referenced.storage_key is None
    rejected(
        build,
        lambda: build.artifact(storage_mode="REFERENCED", external_path="C:/photos/b.jpg"),
        check("ck_artifacts_location"),
    )


def test_available_managed_artifact_must_be_verified(build: Builder) -> None:
    pending = build.artifact(state="PENDING", sha256=None, size_bytes=None)
    assert pending.sha256 is None
    rejected(
        build, lambda: build.artifact(sha256=None), check("ck_artifacts_available_managed_verified")
    )
    rejected(
        build,
        lambda: build.artifact(size_bytes=None),
        check("ck_artifacts_available_managed_verified"),
    )


def test_artifact_hash_must_be_32_bytes(build: Builder) -> None:
    rejected(build, lambda: build.artifact(sha256=b"short"), check("ck_artifacts_sha256_length"))


def test_managed_storage_keys_are_unique(build: Builder) -> None:
    build.artifact(storage_key="originals/one")
    rejected(
        build, lambda: build.artifact(storage_key="originals/one"), unique("artifacts.storage_key")
    )


def test_source_display_name_must_not_be_blank(build: Builder) -> None:
    rejected(
        build, lambda: build.source(display_name="   "), check("ck_sources_display_name_not_empty")
    )


def test_source_media_facts_must_not_be_negative(build: Builder) -> None:
    rejected(build, lambda: build.source(width=-1), check("ck_sources_width_non_negative"))


def test_source_original_artifact_cannot_be_deleted(build: Builder) -> None:
    source = build.source()
    rejected(
        build,
        lambda: build.session.execute(
            delete(Artifact).where(Artifact.id == source.original_artifact_id)
        ),
        "FOREIGN KEY",
    )


def test_deleting_a_thumbnail_artifact_clears_the_source_reference(build: Builder) -> None:
    thumbnail = build.artifact(kind="THUMBNAIL")
    source = build.source(thumbnail_artifact_id=thumbnail.id)
    build.session.execute(delete(Artifact).where(Artifact.id == thumbnail.id))
    build.session.expire_all()
    assert build.session.scalar(select(Source.thumbnail_artifact_id)) is None
    assert build.session.get(Source, source.id) is not None


# --- processing provenance -------------------------------------------------------------------


def test_each_snapshot_belongs_to_exactly_one_run(build: Builder) -> None:
    run = build.run()
    rejected(
        build,
        lambda: build.run(configuration_snapshot_id=run.configuration_snapshot_id),
        unique("processing_runs.configuration_snapshot_id"),
    )


def test_only_one_running_segment_per_run(build: Builder) -> None:
    run = build.run()
    build.segment(run, 0, "COMPLETED")
    build.segment(run, 1, "RUNNING")
    # The partial index (one running per run), not the (run, ordinal) index.
    rejected(
        build,
        lambda: build.segment(run, 2, "RUNNING"),
        unique("execution_segments.processing_run_id"),
    )


def test_segment_ordinals_are_unique_within_a_run(build: Builder) -> None:
    run = build.run()
    build.segment(run, 0, "COMPLETED")
    rejected(
        build,
        lambda: build.segment(run, 0, "FAILED"),
        unique("execution_segments.processing_run_id", "execution_segments.ordinal"),
    )


def test_only_one_valid_final_checkpoint_per_run(build: Builder) -> None:
    run = build.run()
    build.checkpoint(run, 0, "FINAL", "INVALIDATED")
    build.checkpoint(run, 1, "FINAL", "VALID")
    build.checkpoint(run, 2, "INTERMEDIATE", "VALID")
    rejected(
        build,
        lambda: build.checkpoint(run, 3, "FINAL", "VALID"),
        unique("processing_checkpoints.processing_run_id"),
    )


def test_run_cannot_point_at_a_missing_checkpoint(build: Builder) -> None:
    rejected(build, lambda: build.run(current_checkpoint_id=uuid.uuid4()), "FOREIGN KEY")


# --- jobs, catalog, settings -----------------------------------------------------------------


def test_job_progress_cannot_be_negative(build: Builder) -> None:
    rejected(
        build, lambda: build.job(progress_completed=-1), check("ck_jobs_completed_non_negative")
    )
    rejected(build, lambda: build.job(progress_total=-1), check("ck_jobs_total_non_negative"))


def test_job_progress_cannot_exceed_total(build: Builder) -> None:
    job = build.job(progress_completed=3, progress_total=3)
    assert job.progress_completed == job.progress_total
    rejected(
        build,
        lambda: build.job(progress_completed=4, progress_total=3),
        check("ck_jobs_completed_within_total"),
    )


def test_job_retry_links_to_an_existing_previous_job(build: Builder) -> None:
    first = build.job(state="FAILED")
    retry = build.job(previous_job_id=first.id, attempt_number=2)
    assert retry.previous_job_id == first.id
    rejected(build, lambda: build.job(previous_job_id=uuid.uuid4()), "FOREIGN KEY")


def test_representation_space_rules(build: Builder) -> None:
    rejected(
        build,
        lambda: build.representation_space(dimension=0),
        check("ck_representation_spaces_dimension_positive"),
    )
    rejected(
        build,
        lambda: build.representation_space(metric="L2"),
        check("ck_representation_spaces_metric"),
    )


def test_settings_tables_are_singletons(db_session: Session, clock: FrozenClock) -> None:
    db_session.add(ProcessingSettings(id=1, updated_at=clock()))
    db_session.flush()
    db_session.add(ProcessingSettings(id=2, updated_at=clock()))
    with pytest.raises(IntegrityError, match=check("ck_processing_settings_singleton")):
        db_session.flush()
