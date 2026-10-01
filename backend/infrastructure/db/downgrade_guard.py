"""A downgrade must not silently destroy a populated library
(PERSISTENCE_IMPLEMENTATION.md §27; decision 2026-10-01, CONTEXT open question 19, issue 35).

Production never downgrades: recovery moves forward with corrective migrations. A downgrade is a
development and test operation, and it can drop tables or recreate them in an older, narrower shape.
So every revision's `downgrade()` starts by calling `require_destructive_downgrade_allowed`, which
refuses, before any statement of that revision runs, when the library holds user or domain data.
Because each revision is its own transaction and the check comes first, a refused downgrade leaves
the database exactly as it was.

*Populated* means a table other than the internal ones below has a row. Internal tables are
bookkeeping and re-creatable metadata that exist in a freshly initialised library (the migration
stamp, the owed-truncation marker, the settings singletons, the runtime and model catalog and the
representation spaces with their key sequences); a new table is data until it is listed here, so
forgetting to list one errs on the side of refusing.

The explicit override is `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1`. The application never sets it
and nothing in the library reads it back; it is for a developer or a test that really wants the
data gone.
"""

import os

from sqlalchemy import Connection

ALLOW_DESTRUCTIVE_DOWNGRADE_ENV = "FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE"

INTERNAL_TABLES = frozenset(
    {
        "alembic_version",
        "app_state",
        "processing_settings",
        "storage_settings",
        "runtime_settings",
        "components",
        "component_versions",
        "model_exports",
        "installed_model_exports",
        "runtime_variants",
        "runtime_variant_representation_spaces",
        "recognition_calibration_profiles",
        "runtime_packages",
        "runtime_package_installations",
        "representation_spaces",
        "ann_key_sequences",
    }
)


class DestructiveDowngradeRefused(RuntimeError):
    """The library holds data and the downgrade could destroy it."""


def populated_tables(connection: Connection) -> list[str]:
    """The tables, other than the internal ones, that hold at least one row."""
    names = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    ).scalars()
    return [
        name
        for name in names
        if name not in INTERNAL_TABLES
        and connection.exec_driver_sql(f'SELECT 1 FROM "{name}" LIMIT 1').first() is not None  # noqa: S608
    ]


def require_destructive_downgrade_allowed(connection: Connection) -> None:
    """Call first in every revision's `downgrade()`. Raises `DestructiveDowngradeRefused` when the
    library is populated and the override is not set to exactly `1`."""
    if os.environ.get(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV) == "1":
        return
    populated = populated_tables(connection)
    if populated:
        raise DestructiveDowngradeRefused(
            f"refusing to downgrade a library that holds data ({', '.join(populated)}): a "
            "downgrade can destroy it and production recovery moves forward with a new revision. "
            f"For development only, set {ALLOW_DESTRUCTIVE_DOWNGRADE_ENV}=1."
        )
