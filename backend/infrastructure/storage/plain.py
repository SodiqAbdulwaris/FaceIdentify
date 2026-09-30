"""Is this path a plain directory or file: not a link, junction, mount point or other reparse point?

Code that reads, deletes or moves files it owns must not be redirected elsewhere by a link planted
where it expects a real entry. `lstat` is used because `is_dir` and `is_file` follow links.
"""

import os
import stat
from pathlib import Path


def _plain_status(path: Path) -> os.stat_result | None:
    """The entry's own status, or None if it cannot be examined or is a link of any kind."""
    try:
        status = path.lstat()
    except OSError:
        return None
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & reparse:
        return None
    return status


def is_plain_directory(path: Path) -> bool:
    """A real directory. If it cannot be examined, it is not treated as one."""
    status = _plain_status(path)
    return status is not None and stat.S_ISDIR(status.st_mode)


def is_plain_file(path: Path) -> bool:
    """A real regular file. If it cannot be examined, it is not treated as one."""
    status = _plain_status(path)
    return status is not None and stat.S_ISREG(status.st_mode)
