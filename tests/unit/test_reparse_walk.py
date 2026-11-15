"""Reading a link's target without following it, and the walk's remaining refusals (issue #174)."""

import struct
from pathlib import Path

import pytest

from backend.infrastructure.storage import local_path
from backend.infrastructure.storage.local_path import (
    _link_text,
    local_target,
    open_local,
    parse_reparse,
)

SYMLINK = 0xA000000C
MOUNT_POINT = 0xA0000003


def symlink_data(name: str, *, relative: bool = False) -> bytes:
    raw = name.encode("utf-16-le")
    body = struct.pack("<HHHHI", 0, len(raw), 0, len(raw), 1 if relative else 0) + raw
    return struct.pack("<IHH", SYMLINK, len(body), 0) + body


def mount_point_data(name: str) -> bytes:
    raw = name.encode("utf-16-le")
    body = struct.pack("<HHHH", 0, len(raw), 0, len(raw)) + raw
    return struct.pack("<IHH", MOUNT_POINT, len(body), 0) + body


def test_a_symbolic_links_target_is_read_from_its_data() -> None:
    assert parse_reparse(symlink_data(r"\??\C:\real")) == (r"\??\C:\real", False)
    assert parse_reparse(symlink_data(r"..\real", relative=True)) == (r"..\real", True)
    assert parse_reparse(mount_point_data("\\??\\D:\\folder\\")) == ("\\??\\D:\\folder\\", False)


def lone_surrogate() -> bytes:
    data = symlink_data("xy")
    return data[:-4] + b"\x00\xd8" + b"\x00\xd8"  # two unpaired high surrogates


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x01\x02",
        struct.pack("<IHH", 0x80000017, 0, 0) + bytes(24),  # another tag
        symlink_data("")[:20],  # nothing in it
        symlink_data(r"\??\C:\real")[:-2],  # cut short
        symlink_data(r"\??\C:\real")[:6],
        struct.pack("<IHH", SYMLINK, 0, 0) + struct.pack("<HHHHI", 0, 3, 0, 3, 0) + b"abc",
        lone_surrogate(),
    ],
)
def test_data_that_does_not_hold_together_is_not_a_link(data: bytes) -> None:
    assert parse_reparse(data) is None


@pytest.mark.parametrize(
    ("name", "relative", "expected"),
    [
        (r"\??\C:\real", False, r"C:\real"),
        (r"\??\UNC\srv\share\x", False, r"\\srv\share\x"),
        (r"..\real", True, r"C:\base\..\real"),
        (r"\??\Volume{1234}" + "\\", False, None),
        (r"\Device\Mup\x", False, None),
        (r"C:\no-prefix", False, None),
    ],
)
def test_a_links_target_becomes_text_to_resolve_again(
    name: str, relative: bool, expected: str | None
) -> None:
    assert _link_text(name, relative, r"C:\base") == expected


def test_a_link_whose_data_cannot_be_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "via").symlink_to(tmp_path / "real", target_is_directory=True)
    monkeypatch.setattr(local_path, "_reparse_data", lambda handle: None)

    assert local_target(tmp_path / "via" / "a.png") is None


def test_a_handle_that_is_not_a_link_has_no_reparse_data() -> None:
    assert local_path._reparse_data(0) is None


def test_a_file_where_a_folder_should_be_is_not_there(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"x")

    assert local_target(tmp_path / "a.png" / "below") == tmp_path / "a.png" / "below"
    with pytest.raises(FileNotFoundError):
        open_local(tmp_path / "a.png" / "below")


def test_a_step_that_fails_for_another_reason_raises_when_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = local_path._nt_create

    def create(parent: int | None, name: str) -> int:
        if name == "locked":
            raise PermissionError(5, "Access is denied")
        return real(parent, name)

    monkeypatch.setattr(local_path, "_nt_create", create)

    with pytest.raises(PermissionError):
        open_local(tmp_path / "locked" / "a.png")


def test_a_file_that_is_not_a_disk_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.png").write_bytes(b"x")
    monkeypatch.setattr(local_path, "_file_type", lambda handle: 3)  # a pipe

    assert open_local(tmp_path / "a.png") is None


def test_a_link_to_a_volume_is_refused(tmp_path: Path) -> None:
    (tmp_path / "vol").symlink_to("\\\\?\\Volume{00000000-0000-0000-0000-000000000000}\\")

    assert local_target(tmp_path / "vol") is None
    assert open_local(tmp_path / "vol") is None
