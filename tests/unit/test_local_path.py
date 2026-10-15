"""Where a path really leads, decided without going there (issue #174).

Real links and junctions on the real filesystem; the network targets are never contacted (the
`.invalid` host name cannot resolve, and nothing here opens a file).
"""

import os
from pathlib import Path

import pytest

from backend.infrastructure.storage import local_path
from backend.infrastructure.storage.local_path import local_target
from tests.fixtures.links import link_directory

SHARE = r"\\faceidentify-test.invalid\share"


@pytest.mark.parametrize(
    "path",
    [
        SHARE + r"\a.png",  # UNC
        "//faceidentify-test.invalid/share/a.png",  # the same with forward slashes
        r"\/faceidentify-test.invalid/share/a.png",
        r"\\?\UNC\faceidentify-test.invalid\share\a.png",  # extended UNC
        r"\\?\unc\faceidentify-test.invalid\share\a.png",
        r"\\.\pipe\faceidentify",  # a named pipe
        r"\\.\C:\a.png",  # the device namespace, even for a drive
        r"\\?\GLOBALROOT\Device\HarddiskVolume1\a.png",
        r"\\?\Volume{00000000-0000-0000-0000-000000000000}\a.png",
    ],
)
def test_network_and_device_forms_are_refused(path: str) -> None:
    assert local_target(path) is None


def test_a_local_path_is_its_own_target(tmp_path: Path) -> None:
    picture = tmp_path / "a.png"

    assert local_target(picture) == picture  # it need not exist
    assert local_target(str(picture)) == picture


def test_an_extended_drive_path_is_local(tmp_path: Path) -> None:
    picture = tmp_path / "a.png"

    assert local_target("\\\\?\\" + str(picture)) == picture


def test_a_relative_path_is_taken_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert local_target("a.png") == tmp_path / "a.png"


def test_a_junction_to_a_local_folder_leads_into_it(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link_directory(tmp_path / "pictures", real)

    assert local_target(tmp_path / "pictures" / "a.png") == real / "a.png"


def test_a_symlink_to_a_share_is_refused(tmp_path: Path) -> None:
    (tmp_path / "remote.png").symlink_to(SHARE + r"\a.png")

    assert local_target(tmp_path / "remote.png") is None


def test_a_directory_link_to_a_share_is_refused_wherever_it_is_along_the_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "share").symlink_to(SHARE, target_is_directory=True)
    (tmp_path / "outer").mkdir()

    assert local_target(tmp_path / "share" / "deeper" / "a.png") is None
    link_directory(tmp_path / "outer" / "via", tmp_path)  # a junction, then the share link
    assert local_target(tmp_path / "outer" / "via" / "share" / "a.png") is None


def test_a_relative_link_is_followed_from_where_it_is(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "up").symlink_to(Path("..") / "real", target_is_directory=True)

    assert local_target(tmp_path / "sub" / "up" / "a.png") == tmp_path / "real" / "a.png"


def test_a_link_loop_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")

    assert local_target(tmp_path / "a") is None


def test_a_mapped_network_drive_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A mapped drive cannot be made in a test without a share; the drive type is what decides.
    drive = Path(os.path.abspath(tmp_path)).drive
    monkeypatch.setattr(local_path, "_is_network_drive", lambda d: d == drive)

    assert local_target(tmp_path / "a.png") is None


def test_this_machines_own_drive_is_not_a_network_drive(tmp_path: Path) -> None:
    drive = Path(os.path.abspath(tmp_path)).drive

    assert local_path._is_network_drive(drive) is False
    assert local_path._is_network_drive("") is False
