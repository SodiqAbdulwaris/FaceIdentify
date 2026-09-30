"""Temporary job workspaces on the real filesystem (M2: TST-025; IMPLEMENTATION_ARCHITECTURE.md
§16.5; PERSISTENCE_IMPLEMENTATION.md §28 "orphan processing temp workspace").

A workspace is disposable machine-local scratch space. The manager only ever deletes directories it
named itself, and never follows a link out of one.
"""

import os
import stat
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.infrastructure.storage.layout import StorageRoots
from backend.infrastructure.storage.workspaces import (
    OWNERSHIP_MARKER,
    WORKSPACE_SUBDIRECTORIES,
    WorkspaceError,
    WorkspaceManager,
)
from tests.fixtures.links import link_directory


@pytest.fixture
def workspaces(storage_roots: StorageRoots) -> WorkspaceManager:
    return WorkspaceManager(storage_roots)


@pytest.fixture
def precious(tmp_path: Path) -> Path:
    """A folder outside every root, whose contents no cleanup may ever touch."""
    folder = tmp_path / "user documents"
    folder.mkdir()
    (folder / "thesis.txt").write_text("years of work")
    return folder


def new_job() -> uuid.UUID:
    return uuid.uuid4()


# --- allocation ------------------------------------------------------------------------------


def test_a_workspace_is_machine_local_and_has_the_standard_subdirectories(
    workspaces: WorkspaceManager, storage_roots: StorageRoots
) -> None:
    job = new_job()

    path = workspaces.allocate(job)

    assert path == storage_roots.local_state_root / "temp" / "jobs" / job.hex
    assert not path.is_relative_to(storage_roots.library_root)
    assert sorted(child.name for child in path.iterdir()) == sorted(
        [*WORKSPACE_SUBDIRECTORIES, OWNERSHIP_MARKER]
    )
    assert workspaces.path_for(job) == path


def test_allocating_again_returns_the_same_workspace_with_its_files(
    workspaces: WorkspaceManager,
) -> None:
    """A retried or resumed job finds what it already decoded."""
    job = new_job()
    first = workspaces.allocate(job)
    (first / "frames" / "0001.png").write_bytes(b"a decoded frame")

    second = workspaces.allocate(job)

    assert second == first
    assert (second / "frames" / "0001.png").read_bytes() == b"a decoded frame"


def test_each_job_gets_its_own_workspace(workspaces: WorkspaceManager) -> None:
    first, second = new_job(), new_job()

    assert workspaces.allocate(first) != workspaces.allocate(second)
    assert workspaces.existing() == sorted([first, second])


# --- release ---------------------------------------------------------------------------------


def test_release_removes_the_workspace_and_everything_in_it(workspaces: WorkspaceManager) -> None:
    job = new_job()
    path = workspaces.allocate(job)
    (path / "intermediate" / "deep").mkdir()
    (path / "intermediate" / "deep" / "blob.bin").write_bytes(b"x" * 100)

    workspaces.release(job)

    assert not path.exists()
    assert workspaces.existing() == []


def test_releasing_a_workspace_that_does_not_exist_is_a_no_op(workspaces: WorkspaceManager) -> None:
    workspaces.release(new_job())  # not even temp/jobs exists yet
    workspaces.allocate(new_job())
    workspaces.release(new_job())


def test_release_does_not_follow_a_link_out_of_the_workspace(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    job = new_job()
    path = workspaces.allocate(job)
    link_directory(path / "frames" / "shortcut", precious)

    workspaces.release(job)

    assert not path.exists()
    assert (precious / "thesis.txt").read_text() == "years of work"


def test_release_refuses_a_workspace_that_is_itself_a_link(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    job = new_job()
    workspaces.root.mkdir(parents=True)
    link_directory(workspaces.path_for(job), precious)

    with pytest.raises(WorkspaceError, match="not a workspace this manager made"):
        workspaces.release(job)

    assert (precious / "thesis.txt").read_text() == "years of work"


def test_a_directory_the_manager_did_not_mark_is_not_released(
    workspaces: WorkspaceManager,
) -> None:
    job = new_job()
    foreign = workspaces.root / job.hex
    foreign.mkdir(parents=True)
    (foreign / "someone else's.txt").write_text("not ours")

    with pytest.raises(WorkspaceError, match="not a workspace"):
        workspaces.release(job)

    assert (foreign / "someone else's.txt").read_text() == "not ours"


def test_a_read_only_file_does_not_keep_a_workspace_alive(workspaces: WorkspaceManager) -> None:
    """Copying a read-only original keeps the read-only flag; cleanup must still finish."""
    job = new_job()
    readonly = workspaces.allocate(job) / "decode" / "copy-of-original.jpg"
    readonly.write_bytes(b"x")
    os.chmod(readonly, stat.S_IREAD)

    workspaces.release(job)

    assert not workspaces.path_for(job).exists()


# --- allocation refuses what is not its own ---------------------------------------------------


def test_allocation_does_not_write_through_a_link(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    job = new_job()
    workspaces.root.mkdir(parents=True)
    link_directory(workspaces.path_for(job), precious)

    with pytest.raises(WorkspaceError, match="not a directory this manager may use"):
        workspaces.allocate(job)

    assert sorted(child.name for child in precious.iterdir()) == ["thesis.txt"]


def test_allocation_does_not_adopt_a_directory_with_someone_elses_files(
    workspaces: WorkspaceManager,
) -> None:
    job = new_job()
    foreign = workspaces.root / job.hex
    foreign.mkdir(parents=True)
    (foreign / "notes.txt").write_text("not ours")

    with pytest.raises(WorkspaceError, match="was not made by this manager"):
        workspaces.allocate(job)

    assert [child.name for child in foreign.iterdir()] == ["notes.txt"]


def test_allocation_adopts_an_empty_directory_left_by_a_crash(
    workspaces: WorkspaceManager,
) -> None:
    """A crash between creating the directory and marking it leaves an empty one to adopt."""
    job = new_job()
    workspaces.path_for(job).mkdir(parents=True)

    path = workspaces.allocate(job)

    assert (path / OWNERSHIP_MARKER).is_file()
    assert workspaces.existing() == [job]


# --- listing ---------------------------------------------------------------------------------


def test_nothing_exists_before_the_first_allocation(workspaces: WorkspaceManager) -> None:
    assert workspaces.existing() == []
    report = workspaces.remove_orphans(set())
    assert (report.removed, report.kept, report.unowned, report.failed) == ([], [], [], [])


def test_only_directories_the_manager_names_are_workspaces(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    job = new_job()
    workspaces.allocate(job)
    root = workspaces.root
    (root / "notes.txt").write_text("not a workspace")  # a file
    (root / uuid.uuid4().hex.upper()).mkdir()  # not the exact form the manager generates
    (root / "scratch").mkdir()
    (root / uuid.uuid4().hex).mkdir()  # the right name, but never marked as ours
    (root / uuid.uuid4().hex).write_text("a file with a workspace-like name")
    link_directory(root / uuid.uuid4().hex, precious)  # a link posing as a workspace

    assert workspaces.existing() == [job]


# --- orphan cleanup --------------------------------------------------------------------------


def test_orphans_are_removed_and_live_jobs_are_kept(workspaces: WorkspaceManager) -> None:
    live, dead_a, dead_b = new_job(), new_job(), new_job()
    for job in (live, dead_a, dead_b):
        (workspaces.allocate(job) / "frames" / "f.png").write_bytes(b"x")

    report = workspaces.remove_orphans({live})

    assert report.kept == [live]
    assert report.removed == sorted([dead_a, dead_b])
    assert (report.unowned, report.failed) == ([], [])
    assert workspaces.existing() == [live]
    assert (workspaces.path_for(live) / "frames" / "f.png").read_bytes() == b"x"


def test_cleanup_with_no_live_jobs_removes_every_workspace(workspaces: WorkspaceManager) -> None:
    jobs = [new_job() for _ in range(3)]
    for job in jobs:
        workspaces.allocate(job)

    assert workspaces.remove_orphans(set()).removed == sorted(jobs)
    assert workspaces.existing() == []


def test_cleanup_never_deletes_what_it_does_not_own(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    root_entries: dict[str, Callable[[Path], object]] = {
        "notes.txt": lambda p: p.write_text("mine"),
        "scratch": lambda p: p.mkdir(),
        uuid.uuid4().hex: lambda p: p.mkdir(),  # right name, no ownership marker
        uuid.uuid4().hex.upper(): lambda p: p.mkdir(),
        uuid.uuid4().hex: lambda p: link_directory(p, precious),
    }
    workspaces.root.mkdir(parents=True)
    for name, make in root_entries.items():
        make(workspaces.root / name)

    report = workspaces.remove_orphans(set())

    assert sorted(report.unowned) == sorted(root_entries)
    assert report.removed == []
    assert sorted(entry.name for entry in workspaces.root.iterdir()) == sorted(root_entries)
    assert (precious / "thesis.txt").read_text() == "years of work"


def test_cleanup_does_not_follow_links_inside_a_workspace(
    workspaces: WorkspaceManager, precious: Path
) -> None:
    job = new_job()
    link_directory(workspaces.allocate(job) / "crops" / "shortcut", precious)

    assert workspaces.remove_orphans(set()).removed == [job]
    assert (precious / "thesis.txt").read_text() == "years of work"


def test_cleanup_removes_a_read_only_file_too(workspaces: WorkspaceManager) -> None:
    job = new_job()
    readonly = workspaces.allocate(job) / "intermediate" / "copy-of-original.jpg"
    readonly.write_bytes(b"x")
    os.chmod(readonly, stat.S_IREAD)

    report = workspaces.remove_orphans(set())

    assert (report.removed, report.failed) == ([job], [])
    assert workspaces.existing() == []


def test_an_entry_that_cannot_be_examined_is_left_alone(
    workspaces: WorkspaceManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: if the manager cannot tell what something is, it is not its to delete."""
    job = new_job()
    path = workspaces.allocate(job)
    real_lstat = Path.lstat

    def denied(self: Path) -> os.stat_result:
        if self == path:
            raise PermissionError("access is denied")
        return real_lstat(self)

    monkeypatch.setattr(Path, "lstat", denied)

    assert workspaces.existing() == []
    report = workspaces.remove_orphans(set())
    assert (report.removed, report.unowned) == ([], [job.hex])
    monkeypatch.undo()
    assert workspaces.existing() == [job]


def test_a_directory_in_use_is_reported_not_forced(
    workspaces: WorkspaceManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder that is some process's working directory cannot be removed: report, retry later."""
    job = new_job()
    in_use = workspaces.allocate(job) / "decode"
    monkeypatch.chdir(in_use)

    report = workspaces.remove_orphans(set())

    assert [failed for failed, _ in report.failed] == [job]
    monkeypatch.undo()
    assert workspaces.remove_orphans(set()).removed == [job]


def test_one_workspace_that_cannot_be_removed_does_not_stop_the_rest(
    workspaces: WorkspaceManager,
) -> None:
    locked, other = new_job(), new_job()
    stuck = workspaces.allocate(locked) / "decode" / "video.tmp"
    stuck.write_bytes(b"x")
    workspaces.allocate(other)

    with stuck.open("rb"):  # an open handle: Windows refuses to delete the file
        report = workspaces.remove_orphans(set())

    assert report.removed == [other]
    assert [job for job, _ in report.failed] == [locked]
    assert "PermissionError" in report.failed[0][1]
    assert workspaces.existing() == [locked]

    # Once the handle is gone, the next cleanup finishes the job.
    later = workspaces.remove_orphans(set())
    assert (later.removed, later.failed) == ([locked], [])
