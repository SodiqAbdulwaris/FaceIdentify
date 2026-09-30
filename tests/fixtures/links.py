"""Directory links for tests that must prove a path cannot be redirected."""

import sys
from pathlib import Path


def link_directory(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if sys.platform == "win32":  # not os.name: mypy narrows on sys.platform, e.g. in Linux CI
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:  # pragma: no cover - the suite runs on Windows
        link.symlink_to(target, target_is_directory=True)
