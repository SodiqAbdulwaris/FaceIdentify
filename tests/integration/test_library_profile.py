"""A library belongs to one profile, and the other one is refused (issue 137).

Real SQLite, the real lifecycle and the real development catalog; nothing is mocked.
"""

import base64
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import anyio.to_thread
import pytest
from sqlalchemy.orm import Session

from backend.api.development import development_processing, register_development_catalog
from backend.api.library_profile import (
    LIBRARY_PROFILE,
    LibraryProfile,
    LibraryProfileMismatchError,
    claim_library_profile,
)
from backend.api.startup import create_backend_app
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.settings.app_state import AppStateRepository
from tests.factories.models import ModelFactory
from tests.fixtures.api import library_settings
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

DEV, REAL = LibraryProfile.DEVELOPMENT, LibraryProfile.REAL


def a_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


@pytest.fixture
def opened(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs):  # type: ignore[no-untyped-def]
    settings = library_settings(tmp_path, clock, new_id)

    @contextmanager
    def open_it() -> Iterator[OpenLibrary]:
        with open_library(
            library_root=settings.library_root,
            local_state_root=settings.local_state_root,
            clock=clock,
            new_id=new_id,
            retry=settings.retry,
            transaction_retry=settings.transaction_retry,
            index_batch=50,
            max_index_passes=5,
        ) as library:
            yield library

    return open_it


def marker(library: OpenLibrary) -> str | None:
    with Session(library.engine) as session:
        return AppStateRepository(session).get(LIBRARY_PROFILE)


def test_a_new_library_takes_the_profile_it_is_opened_with(opened, clock) -> None:  # type: ignore[no-untyped-def]
    with opened() as library:
        assert marker(library) is None
        claim_library_profile(library, DEV, clock)
        assert marker(library) == "DEVELOPMENT"
        claim_library_profile(library, DEV, clock)  # opening again as the same profile is fine


@pytest.mark.parametrize(("first", "second"), [(DEV, REAL), (REAL, DEV)])
def test_the_other_profile_is_refused_even_after_a_restart(opened, clock, first, second) -> None:  # type: ignore[no-untyped-def]
    with opened() as library:
        claim_library_profile(library, first, clock)
    with opened() as library:
        with pytest.raises(LibraryProfileMismatchError, match=first.value):
            claim_library_profile(library, second, clock)
        assert marker(library) == first.value  # refusing changes nothing


def test_an_unmarked_library_with_development_rows_is_a_development_library(  # type: ignore[no-untyped-def]
    opened, clock, new_id
) -> None:
    with opened() as library:
        register_development_catalog(library, clock, new_id)  # as a library made before the guard
        with pytest.raises(LibraryProfileMismatchError):
            claim_library_profile(library, REAL, clock)
        assert marker(library) is None  # the refusal did not record a guess
        claim_library_profile(library, DEV, clock)
        assert marker(library) == "DEVELOPMENT"


def test_an_unmarked_library_holding_sources_is_a_real_library(opened, clock, new_id) -> None:  # type: ignore[no-untyped-def]
    with opened() as library:
        with Session(library.engine) as session:
            ModelFactory(session, clock, new_id).source()
            session.commit()
        with pytest.raises(LibraryProfileMismatchError):
            claim_library_profile(library, DEV, clock)
        assert marker(library) is None
        claim_library_profile(library, REAL, clock)
        assert marker(library) == "REAL"


def test_an_unrecognised_marker_is_refused(opened, clock) -> None:  # type: ignore[no-untyped-def]
    with opened() as library:
        library.unit_of_work.write(
            lambda session: AppStateRepository(session).set(LIBRARY_PROFILE, "OTHER", now=clock())
        )
        for profile in (DEV, REAL):
            with pytest.raises(LibraryProfileMismatchError):
                claim_library_profile(library, profile, clock)


async def test_the_application_reports_a_refused_library_as_failed(  # type: ignore[no-untyped-def]
    tmp_path, clock, new_id, opened
) -> None:
    settings = library_settings(tmp_path, clock, new_id)
    with opened() as library:
        claim_library_profile(library, REAL, clock)  # a kept library
    app = create_backend_app(a_token(), settings, development_processing(settings))
    async with app.router.lifespan_context(app):
        backend = app.state.backend
        assert await anyio.to_thread.run_sync(backend.settled.wait, 60)
        assert backend.state == "FAILED"
        assert backend.failure == "LibraryProfileMismatchError"
        assert backend.library is not None  # opened, then refused: shutdown still releases it
