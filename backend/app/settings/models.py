"""Settings persistence (PERSISTENCE_IMPLEMENTATION.md §19).

One singleton row per setting group (`CHECK(id = 1)`), updated with optimistic `revision`.
The individual settings are not defined yet, so only the singleton, revision and timestamp
columns exist; typed columns are added with the features that own them.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base
from backend.infrastructure.db.types import UTCDateTime


def _singleton_checks() -> tuple[CheckConstraint, CheckConstraint]:
    return (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )


class ProcessingSettings(Base):
    __tablename__ = "processing_settings"
    __table_args__ = _singleton_checks()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StorageSettings(Base):
    __tablename__ = "storage_settings"
    __table_args__ = _singleton_checks()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"
    __table_args__ = _singleton_checks()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
