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
representation spaces); a new table is data until it is listed here, so forgetting to list one
errs on the side of refusing. `ann_key_sequences` is deliberately *not* internal: it is the
never-reused allocator of index keys, so once a representation has been indexed, dropping it could
let a key be handed out again while an index file survives.

An *offline* run (`alembic downgrade ... --sql`) only prints a script for review and changes
nothing, and it has no database to inspect, so the guard lets it through.

Each revision imports this module, so a later change to the list changes what already shipped
revisions do; that is intended (the list is policy, not schema), as with `types`.

The explicit override is `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1`. The application never sets it
and nothing in the library reads it back; it is for a developer or a test that really wants the
data gone.
"""

import os

from alembic import context
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
    }
)


class DestructiveDowngradeRefused(RuntimeError):
    """The library holds data and the downgrade could destroy it."""


def _quoted(name: str) -> str:
    return name.replace('"', '""')


# An installed model or runtime package keeps its bytes as an `artifacts` row, so a freshly
# initialised library has artifact rows that are catalog, not user data. An artifact counts as data
# unless a catalog table references it *and* no source or observation does (nothing in the schema
# stops one artifact being shared, so a user's thumbnail or crop is never hidden behind a catalog
# row). `NOT EXISTS`, not `NOT IN`: a NULL in a subquery would make `NOT IN` match nothing.
_ROW_QUERIES = {
    "artifacts": """
        SELECT 1 FROM artifacts AS a WHERE
            (NOT EXISTS (SELECT 1 FROM model_exports WHERE artifact_id = a.id)
             AND NOT EXISTS (SELECT 1 FROM installed_model_exports WHERE artifact_id = a.id)
             AND NOT EXISTS (SELECT 1 FROM runtime_package_installations WHERE artifact_id = a.id))
            OR EXISTS (SELECT 1 FROM sources
                       WHERE original_artifact_id = a.id OR thumbnail_artifact_id = a.id)
            OR EXISTS (SELECT 1 FROM observations WHERE face_crop_artifact_id = a.id)
        LIMIT 1
    """,
}


def populated_tables(connection: Connection) -> list[str]:
    """The tables, other than the internal ones, that hold at least one row of data."""
    names = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    ).scalars()
    return [
        name
        for name in names
        if name not in INTERNAL_TABLES
        and connection.exec_driver_sql(
            _ROW_QUERIES.get(name) or f'SELECT 1 FROM "{_quoted(name)}" LIMIT 1'
        ).first()
        is not None
    ]


def require_destructive_downgrade_allowed(connection: Connection) -> None:
    """Call first in every revision's `downgrade()`. Raises `DestructiveDowngradeRefused` when the
    library is populated and the override is not set to exactly `1`."""
    if context.is_offline_mode() or os.environ.get(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV) == "1":
        return
    populated = populated_tables(connection)
    if populated:
        raise DestructiveDowngradeRefused(
            f"refusing to downgrade a library that holds data ({', '.join(populated)}): a "
            "downgrade can destroy it and production recovery moves forward with a new revision. "
            f"For development only, set {ALLOW_DESTRUCTIVE_DOWNGRADE_ENV}=1."
        )
