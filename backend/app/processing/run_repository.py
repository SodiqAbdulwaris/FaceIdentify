"""Repositories for `processing_runs` and `processing_configuration_snapshots`
(PERSISTENCE_IMPLEMENTATION.md §12, §13, §26: "add/get/lock, list transient, create/get immutable
snapshot").

Like the other repositories they join the caller's transaction and never commit. A run's state
changes are the use cases' (they go through the shared optimistic-locked `UPDATE`, §2), so there is
no transition method here.

`lock` is the "lock/reload" of §9 for SQLite, which has one writer and no row locks: it starts the
caller's write transaction *before* it reads, with a write statement that changes nothing, then
returns the row fresh. A transaction that has already read cannot do that: if another writer commits
in between it fails at once with `SQLITE_BUSY_SNAPSHOT` (CONTEXT open question 20), which is why the
lock comes first.

A snapshot is immutable and one per run (§13): nothing here updates or deletes one. One per run is
enforced by the database (`UNIQUE(processing_runs.configuration_snapshot_id)`: a second run cannot
reference a snapshot a run already uses), and the fingerprint is deliberately not unique, so two
runs started with identical settings each keep their own snapshot. Immutability is not yet enforced
by the database (SQLite allows an `UPDATE`); two triggers are decided for revision `0003` (GitHub
issue 51), and until then it rests on nothing calling an update.
"""

import hashlib
import json
import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.processing.models import (
    TRANSIENT_RUN_STATES,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)


def _require_json(value: Any, path: str = "$") -> None:
    """Only what JSON can say exactly: objects with string keys, lists, strings, booleans, null,
    integers and finite floats. `json.dumps` alone would quietly turn an integer key into a string,
    write `NaN` (not JSON), and stringify nothing else, so settings that could not round-trip would
    get a fingerprint anyway."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: object keys must be strings, not {key!r}")
            _require_json(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_json(item, f"{path}[{index}]")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: {value!r} is not a JSON number")
    elif value is not None and not isinstance(value, str | bool | int):
        raise ValueError(f"{path}: {type(value).__name__} is not a JSON value")


def canonical_json_bytes(canonical_json: dict[str, Any]) -> bytes:
    """The bytes a snapshot's fingerprint is taken over: keys sorted, no insignificant whitespace,
    non-ASCII kept as UTF-8, so the same settings always give the same bytes. Anything JSON cannot
    represent exactly (see `_require_json`) is a `ValueError`."""
    _require_json(canonical_json)
    return json.dumps(
        canonical_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        snapshot_id: uuid.UUID,
        schema_version: int,
        canonical_json: dict[str, Any],
        now: datetime,
        created_by_user_action: str | None = None,
    ) -> ProcessingConfigurationSnapshot:
        """Record the resolved settings a run starts with and flush. The fingerprint is the SHA-256
        of `canonical_json_bytes`: a diagnostic, not an authorization token (§13). Settings JSON
        cannot represent exactly are a `ValueError`, before anything is staged."""
        fingerprint = hashlib.sha256(canonical_json_bytes(canonical_json)).digest()
        snapshot = ProcessingConfigurationSnapshot(
            id=snapshot_id,
            schema_version=schema_version,
            canonical_json=canonical_json,
            fingerprint_sha256=fingerprint,
            created_at=now,
            created_by_user_action=created_by_user_action,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def get(self, snapshot_id: uuid.UUID) -> ProcessingConfigurationSnapshot | None:
        return self._session.get(ProcessingConfigurationSnapshot, snapshot_id)


class ProcessingRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: ProcessingRun) -> ProcessingRun:
        """Stage a new run and flush, so its constraints and foreign keys are checked now."""
        self._session.add(run)
        self._session.flush()
        return run

    def get(self, run_id: uuid.UUID) -> ProcessingRun | None:
        """The row as the database has it, not as this session last saw it. Within a transaction
        that has already read, SQLite shows that transaction's snapshot whatever is done here: a
        caller that needs the current row takes `lock` first."""
        return self._session.get(ProcessingRun, run_id, populate_existing=True)

    def lock(self, run_id: uuid.UUID) -> ProcessingRun | None:
        """Take the write lock, then return the run fresh (None if there is none). The lock is held
        until the caller commits or rolls back. Call it as the first statement of the transaction:
        see the module docstring."""
        self._session.execute(
            update(ProcessingRun)
            .where(ProcessingRun.id == run_id)
            .values(revision=ProcessingRun.revision)  # a write that changes nothing
            .execution_options(synchronize_session=False)
        )
        return self.get(run_id)

    def list_transient(self) -> list[ProcessingRun]:
        """Every run that is not over (`TRANSIENT_RUN_STATES`: what startup recovery must inspect),
        least recently updated first."""
        return list(
            self._session.scalars(
                select(ProcessingRun)
                .where(ProcessingRun.state.in_(TRANSIENT_RUN_STATES))
                .order_by(ProcessingRun.updated_at, ProcessingRun.id)
                .execution_options(populate_existing=True)
            )
        )
