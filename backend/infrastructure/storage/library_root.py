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
falls back to a default location, and **a value that is given but unusable is refused, never
replaced by a lower-precedence one**: opening a different library than the caller meant is worse
than refusing. Only `None` (and an environment variable that is empty or whitespace) means "not
given".

The machine-local state root (`%LOCALAPPDATA%/FaceIdentify`: indexes, temp, logs) is separate and
derived data (tech-stack section 15); `FACEIDENTIFY_LOCAL_STATE_ROOT` overrides it for development
and tests. The two roots must not be the same folder or nested in each other
(`validate_distinct_roots`): `StorageRoots.ensure_layout` would mix the trees.
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


def _environment_value(environment: Mapping[str, str], name: str) -> Path | None:
    """The variable as a path, or None if it is unset, empty or only whitespace. A real value is
    taken as it is (surrounding spaces can be part of a name on some systems)."""
    value = environment.get(name)
    return Path(value) if value is not None and value.strip() else None


def _canonical(root: Path) -> Path:
    """The root as the platform reaches it: links and junctions followed and `..` applied the way
    the operating system does (which differs between Windows and POSIX, so `realpath`, not a
    lexical `normpath`). Not strict: a root that does not exist yet is allowed (first run)."""
    return Path(os.path.realpath(root))


def validate_library_root(root: Path) -> Path:
    """The root, if it is usable, in its canonical form: absolute, and either an existing directory
    or a not-yet-existing one directly inside an existing directory (a first-run selection creates
    it, but a path whose parents do not exist is almost certainly a typo and is refused rather than
    created several levels deep). A file is refused. Whether an existing root is writable is not
    checked here: the first write says so, with the operating system's own error."""
    if not root.is_absolute():
        raise InvalidLibraryRootError(f"the library root must be an absolute path: {root}")
    root = _canonical(root)
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
    was cannot be used; an unusable higher-precedence value is never skipped for a lower one."""
    environment = os.environ if environ is None else environ
    for given in (explicit, _environment_value(environment, LIBRARY_ROOT_ENV), persisted):
        if given is not None:
            return validate_library_root(given)
    raise LibraryNotSelectedError(
        f"no library has been selected: pass one, set {LIBRARY_ROOT_ENV}, or choose it in the app"
    )


def resolve_local_state_root(
    *, explicit: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """The machine-local state root: an explicit value, `FACEIDENTIFY_LOCAL_STATE_ROOT`, or
    `%LOCALAPPDATA%/FaceIdentify`. Raises `LibraryRootError` if none can be found."""
    environment = os.environ if environ is None else environ
    root = explicit or _environment_value(environment, LOCAL_STATE_ROOT_ENV)
    if root is None:
        local_app_data = _environment_value(environment, "LOCALAPPDATA")
        if local_app_data is None:
            raise LibraryRootError(
                f"no machine-local state folder: set {LOCAL_STATE_ROOT_ENV} (LOCALAPPDATA is unset)"
            )
        root = local_app_data / APP_DIRECTORY_NAME
    if not root.is_absolute():
        raise InvalidLibraryRootError(f"the local state root must be an absolute path: {root}")
    return _canonical(root)


def validate_distinct_roots(library_root: Path, local_state_root: Path) -> None:
    """The two roots must be different folders and neither may sit inside the other (compared
    canonically; a Windows path compares case-insensitively by itself)."""
    library, local = _canonical(library_root), _canonical(local_state_root)
    if library == local or library in local.parents or local in library.parents:
        raise InvalidLibraryRootError(
            f"the library ({library_root}) and the machine-local state ({local_state_root}) must"
            " be separate folders, neither inside the other"
        )
