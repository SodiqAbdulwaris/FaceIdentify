"""The worker's GPU directory activation (backend/ml/worker/gpu_path.py)."""

import os
import sys
from pathlib import Path

import pytest

from backend.ml.worker import gpu_path


class Handle:
    """What `os.add_dll_directory` returns: the directory leaves the search path when closed."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


handles: list[Handle] = []


@pytest.fixture
def dll_dirs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    added: list[str] = []
    handles.clear()

    def add(directory: str) -> Handle:
        added.append(directory)
        handle = Handle()
        handles.append(handle)
        return handle

    monkeypatch.setattr(os, "add_dll_directory", add, raising=False)
    monkeypatch.setattr(gpu_path, "_dll_handles", [])
    monkeypatch.setattr(sys, "path", list(sys.path))
    return added


def test_unset_or_missing_directory_changes_nothing(tmp_path: Path, dll_dirs: list[str]) -> None:
    before = list(sys.path)
    assert gpu_path.activate({}) is None
    assert gpu_path.activate({gpu_path.GPU_DIR_ENV: str(tmp_path / "absent")}) is None
    assert sys.path == before
    assert dll_dirs == []


def test_directory_goes_first_on_the_path_and_each_bin_is_registered(
    tmp_path: Path, dll_dirs: list[str]
) -> None:
    (tmp_path / "nvidia" / "cudnn" / "bin").mkdir(parents=True)
    (tmp_path / "nvidia" / "cublas" / "bin").mkdir(parents=True)
    (tmp_path / "nvidia" / "empty").mkdir(parents=True)
    environ = {gpu_path.GPU_DIR_ENV: str(tmp_path), "PATH": "base"}

    assert gpu_path.activate(environ) == tmp_path
    assert gpu_path.activate(environ) == tmp_path  # twice: the path gets one entry

    assert sys.path[0] == str(tmp_path)
    assert sys.path.count(str(tmp_path)) == 1
    assert [Path(d).parent.name for d in dll_dirs[:2]] == ["cublas", "cudnn"]
    assert environ["PATH"].endswith("base")
    assert "cublas" in environ["PATH"].split(os.pathsep)[0]


def test_a_directory_without_nvidia_libraries_leaves_the_search_path_alone(
    tmp_path: Path, dll_dirs: list[str]
) -> None:
    environ = {gpu_path.GPU_DIR_ENV: str(tmp_path), "PATH": "base"}
    assert gpu_path.activate(environ) == tmp_path
    assert dll_dirs == []
    assert environ["PATH"] == "base"


def test_the_dll_handles_are_kept_open_for_the_life_of_the_process(
    tmp_path: Path, dll_dirs: list[str]
) -> None:
    (tmp_path / "nvidia" / "cudnn" / "bin").mkdir(parents=True)

    gpu_path.activate({gpu_path.GPU_DIR_ENV: str(tmp_path), "PATH": ""})

    assert len(gpu_path._dll_handles) == 1
    assert not any(handle.closed for handle in handles)
