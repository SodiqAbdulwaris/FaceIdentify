"""Which profile a library belongs to, and the refusal to open it in the other one (issue 137).

The development profile registers a fake catalog and fake perception in the library's own database
(`backend/api/development.py`), so a library it has touched must never be mistaken for a real one,
and a library that holds real data must never gain fake catalog rows. A library carries one
`library_profile` marker in `app_state`, written the first time a backend opens it and checked on
every open afterwards. There is no override: a development library and a real one are different
libraries. Nothing here cleans up development data (deliberately unsolved).

A library with no marker (one made before this guard) is classified from what it holds: development
catalog rows mean DEVELOPMENT, imported sources without them mean REAL, and an empty one takes the
profile it is being opened with.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from backend.app.lifecycle import OpenLibrary
from backend.app.runtime.models import Component
from backend.app.settings.app_state import AppStateRepository
from backend.app.sources.models import Source

LIBRARY_PROFILE: Final = "library_profile"
# The development catalog's component keys (backend/api/development.py owns them).
DEVELOPMENT_COMPONENT_KEYS: Final = ("development-face-detector", "development-face-embedder")


class LibraryProfile(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    REAL = "REAL"


class LibraryProfileMismatchError(RuntimeError):
    """The library belongs to the other profile. The message names profiles, never a path."""


def claim_library_profile(
    library: OpenLibrary, profile: LibraryProfile, clock: Callable[[], datetime]
) -> None:
    """Record the library's profile on first use, or refuse it if it belongs to the other one."""
    now = clock()
    library.unit_of_work.write(lambda session: _claim(session, profile, now))


def _claim(session: Session, requested: LibraryProfile, now: datetime) -> None:
    state = AppStateRepository(session)
    stored = state.get(LIBRARY_PROFILE)
    if stored is None:
        stored = (_classified(session) or requested).value
        state.set(LIBRARY_PROFILE, stored, now=now)
    if stored != requested.value:
        raise LibraryProfileMismatchError(
            f"this library is a {stored} library and cannot be opened as a {requested.value} one"
        )


def _classified(session: Session) -> LibraryProfile | None:
    if session.scalar(select(exists().where(Component.key.in_(DEVELOPMENT_COMPONENT_KEYS)))):
        return LibraryProfile.DEVELOPMENT
    if session.scalar(select(exists().where(Source.id.is_not(None)))):
        return LibraryProfile.REAL
    return None
