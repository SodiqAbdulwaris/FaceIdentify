"""SettingsRepository: the singleton setting groups (PERSISTENCE_IMPLEMENTATION.md §19, §26:
"singleton group reads/updates").

There is one row per group (`processing_settings`, `storage_settings`, `runtime_settings`), each
with `CHECK(id = 1)` and an optimistic `revision`. Like the other repositories it joins the caller's
transaction and never commits, and every change is one statement decided by the database.

* `bootstrap` creates the rows that are missing ("Bootstrap inserts the rows transactionally"):
  one `INSERT ... ON CONFLICT DO NOTHING` per group, so a repeat, or two processes racing,
  changes nothing.
* `update` is the shared optimistic-locked `UPDATE` (§2): it applies only at the revision the caller
  read, bumps it, and stamps `updated_at`. The settings themselves are not defined yet, so the
  groups have no value columns; a name that is not a column of the group is a `ValueError`, so a
  typo can never be silently dropped, and the first typed settings need no change here.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.settings.models import ProcessingSettings, RuntimeSettings, StorageSettings
from backend.infrastructure.db.optimistic import optimistic_locked_update

_MANAGED_COLUMNS = {"id", "revision", "updated_at"}


class SettingsGroup(StrEnum):
    PROCESSING = "PROCESSING"
    STORAGE = "STORAGE"
    RUNTIME = "RUNTIME"


_MODELS: dict[SettingsGroup, type[Any]] = {
    SettingsGroup.PROCESSING: ProcessingSettings,
    SettingsGroup.STORAGE: StorageSettings,
    SettingsGroup.RUNTIME: RuntimeSettings,
}


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def bootstrap(self, *, now: datetime) -> list[SettingsGroup]:
        """Create every group row that does not exist yet, at revision 1; return the groups it
        created (empty on a repeat)."""
        created: list[SettingsGroup] = []
        for group, model in _MODELS.items():
            inserted = self._session.execute(
                sqlite_insert(model)
                .values(id=1, updated_at=now)
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(model.id)
            ).scalar_one_or_none()
            if inserted is not None:
                created.append(group)
        return created

    def get(self, group: SettingsGroup) -> Any | None:
        """The group's row as the database has it now (None before `bootstrap`)."""
        return self._session.get(_MODELS[group], 1, populate_existing=True)

    def update(
        self, group: SettingsGroup, *, expected_revision: int, now: datetime, **values: Any
    ) -> bool:
        """Apply `values` to the group if its revision is `expected_revision`, bump the revision and
        stamp `updated_at`: one guarded `UPDATE`. False if the revision was stale (or the group was
        never bootstrapped). A name that is not a setting of the group is a `ValueError`. Re-read
        the row with `get`: no in-memory copy is updated. With no `values` it still bumps the
        revision and stamps `updated_at` (a touch)."""
        model = _MODELS[group]
        known = {column.key for column in inspect(model).mapper.column_attrs} - _MANAGED_COLUMNS
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"{group} has no setting named {', '.join(unknown)}")
        return bool(
            optimistic_locked_update(
                self._session,
                model,
                1,
                expected_revision=expected_revision,
                values={**values, "updated_at": now},
            )
        )
