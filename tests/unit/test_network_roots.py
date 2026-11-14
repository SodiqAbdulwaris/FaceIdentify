"""Approved network roots: what can be approved and how a path is compared (issue #174, PR A)."""

import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.runtime.network_roots import (
    FILE_NAME,
    NetworkRootInvalidError,
    NetworkRootNotFoundError,
    NetworkRoots,
    unc_parts,
)

NOW = datetime(2026, 11, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def nothing_is_contacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Approving and comparing are text only: a call that reaches a host or a path on one fails."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a host was contacted")

    for name in ("getaddrinfo", "gethostbyname", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)
    real_stat = os.stat

    def stat(path: object, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path).replace("/", "\\").startswith("\\\\"):
            raise AssertionError("a network path was touched")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", stat)


@pytest.mark.parametrize(
    "text",
    [
        r"\\server\share",
        "//SERVER/Share/",
        r"\\server\share\.",
        r"\\?\UNC\server\share",
        r"\\?\unc\Server\SHARE",
        r"\\server\\share",  # (a doubled separator)
        "\\\\server/share",
    ],
)
def test_one_share_has_one_name_however_it_is_written(text: str) -> None:
    assert [p.upper() for p in unc_parts(text) or ()] == ["SERVER", "SHARE"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "server",
        r"\\server",
        r"\\server\\",
        r"C:\photos",
        r"\\.\pipe\name",
        r"\\.\GLOBALROOT\Device\x",
        r"\\?\GLOBALROOT\Device\x",
        r"\\?\Volume{1234}\x",
        r"\\?\C:\photos",
        r"\\server\share\..\other",
        r"\\server\share\nul",
        r"\\server\share\a:b",
        r"\\server\share\*",
        r"\\server\share\dir.",
        r"\\server\share\dir ",
        r"\\server@SSL\share",
        r"\\server@8080\share",
        "\\\\server\\share\\a\x00b",
        "http://server/share",
    ],
)
def test_what_is_not_a_share_or_a_folder_on_one_cannot_be_approved(
    text: str, tmp_path: Path
) -> None:
    assert unc_parts(text) is None
    with pytest.raises(NetworkRootInvalidError):
        NetworkRoots(tmp_path).add(text, now=NOW)
    assert not (tmp_path / FILE_NAME).exists()


def test_a_root_covers_itself_and_what_is_below_it_and_nothing_else(tmp_path: Path) -> None:
    roots = NetworkRoots(tmp_path)
    roots.add(r"\\Server\Photos\2026", now=NOW)

    assert roots.approves(r"\\server\photos\2026")
    assert roots.approves("//SERVER/PHOTOS/2026/trip/a.jpg")
    assert roots.approves(r"\\?\UNC\server\photos\2026\a.jpg")
    assert not roots.approves(r"\\server\photos")  # above the root
    assert not roots.approves(r"\\server\photos\2026x\a.jpg")  # a longer name, not a child
    assert not roots.approves(r"\\server\photos\2025\a.jpg")
    assert not roots.approves(r"\\server2\photos\2026\a.jpg")
    assert not roots.approves(r"\\server\photos\2026\..\2025\a.jpg")
    assert not roots.approves(r"C:\photos")


def test_a_whole_share_covers_every_folder_in_it(tmp_path: Path) -> None:
    roots = NetworkRoots(tmp_path)
    roots.add(r"\\nas\family", now=NOW)

    assert roots.approves(r"\\NAS\Family\any\folder\a.jpg")
    assert not roots.approves(r"\\nas\other\a.jpg")


def test_approving_twice_keeps_the_first_approval_and_one_entry(tmp_path: Path) -> None:
    roots = NetworkRoots(tmp_path)
    first = roots.add(r"\\nas\family", now=NOW)
    again = roots.add("//NAS/Family/", now=datetime(2027, 1, 1, tzinfo=UTC))

    assert again == first
    assert roots.approved() == [first]
    assert first.path == r"\\nas\family"


def test_the_list_survives_a_restart_and_a_revoked_root_is_gone(tmp_path: Path) -> None:
    one = NetworkRoots(tmp_path).add(r"\\nas\family", now=NOW)
    two = NetworkRoots(tmp_path).add(r"\\nas\work\scans", now=NOW)

    again = NetworkRoots(tmp_path)
    assert again.approved() == [one, two]
    again.revoke(one.id)

    assert NetworkRoots(tmp_path).approved() == [two]
    assert not NetworkRoots(tmp_path).approves(r"\\nas\family\a.jpg")
    assert not list(tmp_path.glob("*.partial"))


def test_revoking_what_is_not_approved_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(NetworkRootNotFoundError):
        NetworkRoots(tmp_path).revoke("0" * 16)


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"roots": 3}', '{"roots": [{"path": "C:\\\\x", "approved_at": "t"}]}'],
)
def test_a_damaged_file_approves_nothing(tmp_path: Path, content: str) -> None:
    (tmp_path / FILE_NAME).write_text(content, encoding="utf-8")

    roots = NetworkRoots(tmp_path)

    assert roots.approved() == []
    assert not roots.approves(r"\\nas\family\a.jpg")


def test_a_file_cannot_widen_what_was_approved(tmp_path: Path) -> None:
    """The file is read through the same validation as an approval, so a hand-edited entry that
    would be refused if added (a device namespace) approves nothing."""
    (tmp_path / FILE_NAME).write_text(
        '{"roots": [{"path": "\\\\\\\\.\\\\pipe\\\\x", "approved_at": "t"}]}', encoding="utf-8"
    )

    assert NetworkRoots(tmp_path).approved() == []
