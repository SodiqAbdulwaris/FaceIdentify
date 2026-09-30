"""Which rows point at an artifact through a foreign key, read from the schema.

An artifact that a row references is in use. Listing the referencing columns by hand would go stale
the first time a table gains an `artifacts.id` foreign key, and a stale list means cleanup deleting
bytes something still needs. So the columns are discovered from `Base.metadata`, and a test pins the
current set so that a new one has to be looked at.

This covers *declared foreign keys only*. A reference that keeps an artifact's bytes alive must
therefore be a foreign key: one hidden in a JSON payload, a storage-key string or a table outside
this metadata is invisible here and would not protect the bytes. No such reference exists today.
"""

from sqlalchemy import Column, ColumnElement, and_, exists

import backend.app.models  # noqa: F401  (imports every feature's models so the metadata is complete)
from backend.app.sources.models import Artifact
from backend.infrastructure.db.engine import Base


def artifact_reference_columns() -> list[Column[object]]:
    """Every foreign-key column, in any table, that points at `artifacts.id`."""
    return [
        foreign_key.parent
        for table in Base.metadata.sorted_tables
        for foreign_key in table.foreign_keys
        if foreign_key.column is Artifact.__table__.c.id
    ]


def unreferenced_artifacts() -> ColumnElement[bool]:
    """A condition, for use inside a statement over `artifacts`, that no row references the row."""
    return and_(
        *(~exists().where(column == Artifact.id) for column in artifact_reference_columns())
    )
