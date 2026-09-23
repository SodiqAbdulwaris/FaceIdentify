"""The built SQLite schema matches PERSISTENCE_IMPLEMENTATION.md §20 and §21.

§20 defines the delete rules and §21 the required indexes.

Read back from SQLite itself (PRAGMA), so a model that silently loses an `ondelete` or an index
fails here even when no behavioural test happens to exercise it. SQLite reports a missing
`ondelete` as `NO ACTION`, which also blocks deletes, so behavioural tests alone cannot tell it
apart from `RESTRICT`.
"""

from sqlalchemy import Engine
from sqlalchemy.orm import MANYTOONE

from backend.app.models import Base
from backend.app.processing.models import TRANSIENT_RUN_STATES

# (table, column) -> (referenced table, ON DELETE), for every foreign key in the schema.
EXPECTED_FOREIGN_KEYS = {
    ("sources", "original_artifact_id"): ("artifacts", "RESTRICT"),
    ("sources", "thumbnail_artifact_id"): ("artifacts", "SET NULL"),
    ("sources", "current_processing_run_id"): ("processing_runs", "SET NULL"),
    ("processing_runs", "source_id"): ("sources", "RESTRICT"),
    ("processing_runs", "configuration_snapshot_id"): (
        "processing_configuration_snapshots",
        "RESTRICT",
    ),
    ("processing_runs", "parent_run_id"): ("processing_runs", "RESTRICT"),
    ("processing_runs", "current_checkpoint_id"): ("processing_checkpoints", "SET NULL"),
    ("execution_segments", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("execution_segments", "runtime_variant_id"): ("runtime_variants", "RESTRICT"),
    ("processing_checkpoints", "processing_run_id"): ("processing_runs", "CASCADE"),
    ("processing_checkpoints", "execution_segment_id"): ("execution_segments", "RESTRICT"),
    ("jobs", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("jobs", "previous_job_id"): ("jobs", "RESTRICT"),
    ("component_versions", "component_id"): ("components", "RESTRICT"),
    ("model_exports", "component_version_id"): ("component_versions", "RESTRICT"),
    ("model_exports", "artifact_id"): ("artifacts", "RESTRICT"),
    ("installed_model_exports", "model_export_id"): ("model_exports", "RESTRICT"),
    ("installed_model_exports", "artifact_id"): ("artifacts", "RESTRICT"),
    ("runtime_variants", "model_export_id"): ("model_exports", "RESTRICT"),
    ("runtime_variant_representation_spaces", "runtime_variant_id"): (
        "runtime_variants",
        "CASCADE",
    ),
    ("runtime_variant_representation_spaces", "representation_space_id"): (
        "representation_spaces",
        "CASCADE",
    ),
    ("recognition_calibration_profiles", "representation_space_id"): (
        "representation_spaces",
        "RESTRICT",
    ),
    ("runtime_package_installations", "runtime_package_id"): ("runtime_packages", "RESTRICT"),
    ("runtime_package_installations", "artifact_id"): ("artifacts", "RESTRICT"),
    ("representation_spaces", "component_version_id"): ("component_versions", "RESTRICT"),
    # Memory, identity and people (M1 PR 2).
    ("ann_key_sequences", "representation_space_id"): ("representation_spaces", "RESTRICT"),
    ("observations", "source_id"): ("sources", "RESTRICT"),
    ("observations", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("observations", "execution_segment_id"): ("execution_segments", "RESTRICT"),
    ("observations", "face_crop_artifact_id"): ("artifacts", "SET NULL"),
    ("observations", "detector_component_version_id"): ("component_versions", "RESTRICT"),
    ("observations", "superseded_by_run_id"): ("processing_runs", "RESTRICT"),
    ("representations", "observation_id"): ("observations", "CASCADE"),
    ("representations", "identity_id"): ("identities", "RESTRICT"),
    ("representations", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("representations", "execution_segment_id"): ("execution_segments", "RESTRICT"),
    ("representations", "representation_space_id"): ("representation_spaces", "RESTRICT"),
    ("occurrences", "source_id"): ("sources", "RESTRICT"),
    ("occurrences", "identity_id"): ("identities", "RESTRICT"),
    ("occurrences", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("occurrences", "representative_observation_id"): ("observations", "SET NULL"),
    ("occurrence_observations", "occurrence_id"): ("occurrences", "CASCADE"),
    ("occurrence_observations", "observation_id"): ("observations", "RESTRICT"),
    ("index_operations", "representation_id"): ("representations", "RESTRICT"),
    ("index_operations", "representation_space_id"): ("representation_spaces", "RESTRICT"),
    ("identities", "created_by_processing_run_id"): ("processing_runs", "RESTRICT"),
    ("identities", "representative_observation_id"): ("observations", "SET NULL"),
    ("identities", "merged_into_identity_id"): ("identities", "RESTRICT"),
    ("identity_lineage", "from_identity_id"): ("identities", "RESTRICT"),
    ("identity_lineage", "to_identity_id"): ("identities", "RESTRICT"),
    ("identity_lineage", "evidence_id"): ("evidence", "RESTRICT"),
    ("evidence", "processing_run_id"): ("processing_runs", "RESTRICT"),
    ("evidence", "source_id"): ("sources", "RESTRICT"),
    ("evidence", "subject_identity_id"): ("identities", "RESTRICT"),
    ("evidence", "subject_person_id"): ("people", "RESTRICT"),
    ("evidence", "calibration_profile_id"): ("recognition_calibration_profiles", "RESTRICT"),
    ("evidence_representations", "evidence_id"): ("evidence", "CASCADE"),
    ("evidence_representations", "representation_id"): ("representations", "RESTRICT"),
    ("evidence_candidates", "evidence_id"): ("evidence", "CASCADE"),
    ("evidence_candidates", "representation_id"): ("representations", "RESTRICT"),
    ("evidence_candidates", "identity_id"): ("identities", "RESTRICT"),
    ("identity_person_associations", "identity_id"): ("identities", "RESTRICT"),
    ("identity_person_associations", "person_id"): ("people", "RESTRICT"),
    ("identity_person_associations", "evidence_id"): ("evidence", "RESTRICT"),
}

# table -> required non-partial indexes from §21 as (columns, unique). Partial indexes are
# checked by name and predicate in EXPECTED_PARTIAL_INDEXES.
EXPECTED_INDEXES: dict[str, set[tuple[tuple[str, ...], bool]]] = {
    "artifacts": {(("storage_key",), True), (("state", "created_at"), False), (("sha256",), False)},
    "sources": {
        (("state", "created_at", "id"), False),
        (("current_processing_run_id",), False),
        (("original_artifact_id",), False),
    },
    "processing_runs": {(("source_id", "created_at"), False), (("state", "updated_at"), False)},
    "jobs": {
        (("state", "priority", "created_at"), False),
        (("lease_expires_at",), False),
        (("processing_run_id",), False),
    },
    "execution_segments": {(("processing_run_id", "ordinal"), True)},
    "processing_checkpoints": {(("processing_run_id", "ordinal"), True)},
    "observations": {
        (("processing_run_id", "sequence_in_run"), True),
        (("source_id", "state", "created_at"), False),
        (("face_crop_artifact_id",), False),
    },
    "representations": {
        (("ann_key",), True),
        (("representation_space_id", "state", "ann_key"), False),
        (("identity_id", "state"), False),
        (("processing_run_id", "state"), False),
    },
    "occurrences": {
        (("source_id", "state", "created_at"), False),
        (("identity_id", "state", "created_at"), False),
        (("processing_run_id", "state"), False),
    },
    "evidence": {
        (("subject_identity_id", "created_at"), False),
        (("processing_run_id", "created_at"), False),
        (("kind", "created_at"), False),
    },
    "index_operations": {
        (("state", "not_before_at", "created_at"), False),
        (("representation_space_id", "state"), False),
    },
    "people": {(("state", "normalized_name"), False)},
    "identity_person_associations": {(("person_id", "state"), False)},
}

EXPECTED_PARTIAL_INDEXES = {
    "ix_processing_runs_transient_state": (
        "processing_runs",
        False,
        "state IN (" + ", ".join(f"'{state.value}'" for state in TRANSIENT_RUN_STATES) + ")",
    ),
    "uq_execution_segments_one_running_per_run": ("execution_segments", True, "state = 'RUNNING'"),
    "uq_processing_checkpoints_one_valid_final_per_run": (
        "processing_checkpoints",
        True,
        "kind = 'FINAL' AND state = 'VALID'",
    ),
    "uq_identity_person_active": ("identity_person_associations", True, "state = 'ACTIVE'"),
    "uq_index_operations_one_pending_per_representation_operation": (
        "index_operations",
        True,
        "state = 'PENDING'",
    ),
}


def test_foreign_keys_and_delete_rules_match_the_spec(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:
        tables = [
            n for (n,) in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        actual = {
            (table, row[3]): (row[2], row[6])
            for table in tables
            for row in conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})")
        }
    assert actual == EXPECTED_FOREIGN_KEYS


def test_required_indexes_exist(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:
        for table, expected in EXPECTED_INDEXES.items():
            actual = set()
            for row in conn.exec_driver_sql(f"PRAGMA index_list({table})"):
                name, unique, partial = row[1], bool(row[2]), bool(row[4])
                if partial:
                    continue
                columns = tuple(
                    info[2] for info in conn.exec_driver_sql(f"PRAGMA index_info('{name}')")
                )
                actual.add((columns, unique))
            assert expected <= actual, f"{table}: missing {expected - actual}"


def test_required_partial_indexes_exist(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:
        for name, (table, unique, predicate) in EXPECTED_PARTIAL_INDEXES.items():
            sql = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name = ? AND tbl_name = ?",
                (name, table),
            ).scalar()
            assert sql is not None, f"missing partial index {name}"
            assert sql.startswith("CREATE UNIQUE INDEX" if unique else "CREATE INDEX"), name
            assert f"WHERE {predicate}" in sql, name


# Columns with a required database DEFAULT: `revision INTEGER NOT NULL DEFAULT 1` (§2),
# `attempt_number` (§15) and `attempt_count` (starts at zero). Checked in the DDL itself: ORM
# and Core inserts both apply the Python-side default, so an insert-based test cannot tell
# whether the DEFAULT exists.
EXPECTED_DEFAULTS = {
    ("sources", "revision"): "1",
    ("processing_runs", "revision"): "1",
    ("jobs", "attempt_number"): "1",
    ("processing_settings", "revision"): "1",
    ("storage_settings", "revision"): "1",
    ("runtime_settings", "revision"): "1",
    ("identities", "revision"): "1",
    ("people", "revision"): "1",
    ("identity_person_associations", "revision"): "1",
    ("index_operations", "attempt_count"): "0",
}


def test_counter_columns_have_ddl_defaults(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:
        for (table, column), default in sorted(EXPECTED_DEFAULTS.items()):
            info = {row[1]: row for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            assert info[column][3] == 1, f"{table}.{column} must be NOT NULL"
            assert info[column][4] == default, f"{table}.{column} must DEFAULT {default}"


# §22: to-one relationships only, exactly these. Unbounded collections (Source.observations,
# Identity.representations, ...) must not exist; code uses explicit queries instead.
EXPECTED_RELATIONSHIPS = {
    "representations": {
        "observation",
        "identity",
        "representation_space",
        "processing_run",
        "execution_segment",
    },
    "observations": {"source", "processing_run", "execution_segment"},
    "occurrences": {"source", "identity", "processing_run", "representative_observation"},
    "processing_runs": {"source", "configuration_snapshot"},
    "execution_segments": {"processing_run", "runtime_variant"},
    "identity_person_associations": {"identity", "person", "evidence"},
}


def test_orm_relationships_are_exactly_the_bounded_to_one_set() -> None:
    actual = {
        mapper.class_.__tablename__: {
            rel.key for rel in mapper.relationships if rel.direction is MANYTOONE
        }
        for mapper in Base.registry.mappers
    }
    collections = [
        f"{mapper.class_.__name__}.{rel.key}"
        for mapper in Base.registry.mappers
        for rel in mapper.relationships
        if rel.direction is not MANYTOONE
    ]
    assert collections == []
    assert {table: keys for table, keys in actual.items() if keys} == EXPECTED_RELATIONSHIPS
