"""SEC-001: the test suite cannot reach the user's real library or application data."""

import os
from pathlib import Path

import pytest

from tests.conftest import USER_DATA_ENV_VARS
from tests.fixtures.persistence import _require_inside


def test_user_data_locations_point_at_the_sandbox(sandbox_user_data: Path) -> None:
    for name in USER_DATA_ENV_VARS:
        assert Path(os.environ[name]) == sandbox_user_data
    assert Path.home() == sandbox_user_data
    assert Path(os.path.expanduser("~")) == sandbox_user_data


def test_storage_guard_rejects_paths_outside_the_sandbox(tmp_path: Path) -> None:
    assert _require_inside(tmp_path / "library.db", tmp_path) == tmp_path / "library.db"
    with pytest.raises(RuntimeError, match="escaped its sandbox"):
        _require_inside(tmp_path / ".." / "library.db", tmp_path)
