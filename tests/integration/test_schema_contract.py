"""The built SQLite schema matches PERSISTENCE_IMPLEMENTATION.md §20 and §21.

§20 defines the delete rules and §21 the required indexes.

Read back from SQLite itself (PRAGMA), so a model that silently loses an `ondelete` or an index
fails here even when no behavioural test happens to exercise it. SQLite reports a missing
`ondelete` as `NO ACTION`, which also blocks deletes, so behavioural tests alone cannot tell it
apart from `RESTRICT`.
"""

from sqlalchemy import Engine

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
}

EXPECTED_PARTIAL_INDEXES = {
    "ix_processing_runs_transient_state": ("processing_runs", False, "state IN ("),
    "uq_execution_segments_one_running_per_run": ("execution_segments", True, "state = 'RUNNING'"),
    "uq_processing_checkpoints_one_valid_final_per_run": (
        "processing_checkpoints",
        True,
        "kind = 'FINAL' AND state = 'VALID'",
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


# Columns with a spec-required database DEFAULT (§2: `revision INTEGER NOT NULL DEFAULT 1`).
# Checked in the DDL itself: ORM and Core inserts both apply the Python-side default, so an
# insert-based test cannot tell whether the DEFAULT exists.
EXPECTED_DEFAULT_ONE = {
    ("sources", "revision"),
    ("processing_runs", "revision"),
    ("jobs", "attempt_number"),
    ("processing_settings", "revision"),
    ("storage_settings", "revision"),
    ("runtime_settings", "revision"),
}


def test_revision_columns_default_to_one_in_the_ddl(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:
        for table, column in sorted(EXPECTED_DEFAULT_ONE):
            info = {row[1]: row for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            assert info[column][3] == 1, f"{table}.{column} must be NOT NULL"
            assert info[column][4] == "1", f"{table}.{column} must DEFAULT 1"
