"""Resolving the one library root of a backend process (M2: TST-030; CONTEXT open question 17).

An explicit value wins, then the development and test override, then the persisted setting the
shell passes in; with none of them the library has not been chosen (first run) and nothing is
guessed. A root must be absolute and usable: an existing directory, or a new one inside an existing
folder. The machine-local state root has its own override and defaults under `%LOCALAPPDATA%`.
"""

from pathlib import Path

import pytest

from backend.infrastructure.storage.library_root import (
    LIBRARY_ROOT_ENV,
    LOCAL_STATE_ROOT_ENV,
    InvalidLibraryRootError,
    LibraryNotSelectedError,
    LibraryRootError,
    resolve_library_root,
    resolve_local_state_root,
    validate_library_root,
)


def test_the_order_is_explicit_then_the_environment_then_the_persisted_setting(
    tmp_path: Path,
) -> None:
    explicit, from_env, persisted = (tmp_path / name for name in ("explicit", "env", "persisted"))
    environ = {LIBRARY_ROOT_ENV: str(from_env)}

    assert resolve_library_root(explicit=explicit, environ=environ, persisted=persisted) == explicit
    assert resolve_library_root(environ=environ, persisted=persisted) == from_env
    assert resolve_library_root(environ={}, persisted=persisted) == persisted


def test_a_blank_value_counts_as_not_given(tmp_path: Path) -> None:
    persisted = tmp_path / "persisted"

    resolved = resolve_library_root(
        explicit=Path(" "), environ={LIBRARY_ROOT_ENV: "  "}, persisted=persisted
    )

    assert resolved == persisted


def test_the_process_environment_is_used_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LIBRARY_ROOT_ENV, str(tmp_path / "from-process-env"))
    assert resolve_library_root() == tmp_path / "from-process-env"


def test_with_nothing_given_the_library_has_not_been_chosen_and_no_default_is_invented() -> None:
    with pytest.raises(LibraryNotSelectedError, match=LIBRARY_ROOT_ENV):
        resolve_library_root(environ={})


def test_a_relative_root_is_refused() -> None:
    with pytest.raises(InvalidLibraryRootError, match="absolute"):
        validate_library_root(Path("library"))


def test_a_file_is_not_a_library_root(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(InvalidLibraryRootError, match="not a directory"):
        validate_library_root(file)


def test_a_new_folder_in_an_existing_one_is_allowed_but_not_several_levels_deep(
    tmp_path: Path,
) -> None:
    assert validate_library_root(tmp_path / "new") == tmp_path / "new"  # first-run selection
    with pytest.raises(InvalidLibraryRootError, match="does not exist"):
        validate_library_root(tmp_path / "typo" / "library")  # almost certainly a typo
    assert not (tmp_path / "typo").exists()  # and nothing was created


def test_an_existing_directory_is_normalised_and_accepted(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    assert validate_library_root(tmp_path / "a" / ".." / "b") == tmp_path / "b"


def test_the_local_state_root_order_and_default(tmp_path: Path) -> None:
    explicit, from_env, app_data = (tmp_path / name for name in ("explicit", "env", "appdata"))
    environ = {LOCAL_STATE_ROOT_ENV: str(from_env), "LOCALAPPDATA": str(app_data)}

    assert resolve_local_state_root(explicit=explicit, environ=environ) == explicit
    assert resolve_local_state_root(environ=environ) == from_env
    assert resolve_local_state_root(environ={"LOCALAPPDATA": str(app_data)}) == (
        app_data / "FaceIdentify"
    )


def test_the_local_state_root_needs_somewhere_to_live_and_must_be_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(LibraryRootError, match=LOCAL_STATE_ROOT_ENV):
        resolve_local_state_root(environ={})
    with pytest.raises(InvalidLibraryRootError, match="absolute"):
        resolve_local_state_root(environ={LOCAL_STATE_ROOT_ENV: "relative"})

    monkeypatch.delenv(LOCAL_STATE_ROOT_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert resolve_local_state_root() == tmp_path / "FaceIdentify"  # the process environment
