"""AppStateRepository: the durable "WAL truncation owed" marker (PERSISTENCE_IMPLEMENTATION.md §25).

It joins the caller's transaction and never commits, and every change is one statement. The marker
is set in the transaction that clears an erased vector and key, so a crash before the truncating
checkpoint leaves the database saying the cleanup is still owed; it is cleared only after the
checkpoint has succeeded.
"""

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.settings.models import AppState

WAL_TRUNCATION_OWED = "wal_truncation_owed"


class AppStateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def set(self, key: str, value: str, *, now: datetime) -> None:
        """Create or overwrite `key`: one upsert statement."""
        statement = sqlite_insert(AppState).values(key=key, value=value, updated_at=now)
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["key"], set_={"value": value, "updated_at": now}
            )
        )

    def get(self, key: str) -> str | None:
        return self._session.scalar(select(AppState.value).where(AppState.key == key))

    def clear(self, key: str, *, value: str | None = None) -> bool:
        """Delete `key`; with `value`, only if it still holds that value (so a marker set again
        meanwhile is not cleared by an earlier checkpoint). False if nothing was deleted."""
        statement = delete(AppState).where(AppState.key == key)
        if value is not None:
            statement = statement.where(AppState.value == value)
        result = cast("CursorResult[object]", self._session.execute(statement))
        return bool(result.rowcount)
