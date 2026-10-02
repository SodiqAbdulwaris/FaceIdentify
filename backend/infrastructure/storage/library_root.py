"""Where the library lives: one resolved root per backend process (CONTEXT open question 17, decided
2026-10-01 by the owner).

The desktop shell owns library selection and keeps the chosen absolute path in application-level
settings *outside* the library (a library cannot tell the application where it is: that would be
circular). The backend receives exactly one resolved root at startup and it never changes during the
process: every database, artifact, index, runtime, quarantine and lock path derives from it, through
`StorageRoots` (`layout.py`). Changing library means restarting the backend lifecycle.

The order is: an explicit value (what the shell passes), then the development and test override
`FACEIDENTIFY_LIBRARY_ROOT`, then the persisted setting (the shell reads it and passes it in; the
file format is the shell's), and otherwise the library has not been chosen yet (first run). Nothing
falls back to a default location: opening a different library than the user meant is worse than
refusing.

The machine-local state root (`%LOCALAPPDATA%/FaceIdentify`: indexes, temp, logs) is separate and
derived data (tech-stack section 15); `FACEIDENTIFY_LOCAL_STATE_ROOT` overrides it for development
and tests.
"""

import os
from collections.abc import Mapping
from pathlib import Path

LIBRARY_ROOT_ENV = "FACEIDENTIFY_LIBRARY_ROOT"
LOCAL_STATE_ROOT_ENV = "FACEIDENTIFY_LOCAL_STATE_ROOT"
APP_DIRECTORY_NAME = "FaceIdentify"


class LibraryRootError(Exception):
    """The library root cannot be determined or used."""


class LibraryNotSelectedError(LibraryRootError):
    """No library has been chosen yet: the first-run selection is needed."""


class InvalidLibraryRootError(LibraryRootError):
    """A library root was given but cannot be used as one."""


def _first(*candidates: Path | str | None) -> Path | None:
    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return Path(str(candidate).strip())
    return None


def validate_library_root(root: Path) -> Path:
    """The root, if it is usable: absolute, and either an existing directory or a not-yet-existing
    one inside an existing directory (a first-run selection creates it, but a path whose parents do
    not exist is almost certainly a typo and is refused rather than created several levels deep).
    A file or anything that is not a directory is refused."""
    if not root.is_absolute():
        raise InvalidLibraryRootError(f"the library root must be an absolute path: {root}")
    root = Path(os.path.normpath(root))
    if root.exists():
        if not root.is_dir():
            raise InvalidLibraryRootError(f"the library root is not a directory: {root}")
    elif not root.parent.is_dir():
        raise InvalidLibraryRootError(
            f"the folder that should hold the library does not exist: {root.parent}"
        )
    return root


def resolve_library_root(
    *,
    explicit: Path | None = None,
    environ: Mapping[str, str] | None = None,
    persisted: Path | None = None,
) -> Path:
    """The one library root for this process (see the module docstring for the order). Raises
    `LibraryNotSelectedError` when none was given and `InvalidLibraryRootError` when the one that
    was cannot be used."""
    environment = os.environ if environ is None else environ
    root = _first(explicit, environment.get(LIBRARY_ROOT_ENV), persisted)
    if root is None:
        raise LibraryNotSelectedError(
            "no library has been selected: pass one, set "
            f"{LIBRARY_ROOT_ENV}, or choose it in the app"
        )
    return validate_library_root(root)


def resolve_local_state_root(
    *, explicit: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """The machine-local state root: an explicit value, `FACEIDENTIFY_LOCAL_STATE_ROOT`, or
    `%LOCALAPPDATA%/FaceIdentify`. Raises `LibraryRootError` if none can be found."""
    environment = os.environ if environ is None else environ
    root = _first(explicit, environment.get(LOCAL_STATE_ROOT_ENV))
    if root is None:
        local_app_data = _first(environment.get("LOCALAPPDATA"))
        if local_app_data is None:
            raise LibraryRootError(
                f"no machine-local state folder: set {LOCAL_STATE_ROOT_ENV} (LOCALAPPDATA is unset)"
            )
        root = local_app_data / APP_DIRECTORY_NAME
    if not root.is_absolute():
        raise InvalidLibraryRootError(f"the local state root must be an absolute path: {root}")
    return Path(os.path.normpath(root))
