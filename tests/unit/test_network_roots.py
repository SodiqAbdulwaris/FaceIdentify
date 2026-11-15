"""Approved network roots: what can be approved and how a path is compared (issue #174, PR A)."""

import os
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.runtime.network_roots import (
    FILE_NAME,
    NetworkRootInvalidError,
    NetworkRootNotFoundError,
    NetworkRoots,
    NetworkRootsUnreadableError,
)
from backend.infrastructure.storage.unc import unc_parts

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
    real_lstat, real_scandir = os.lstat, os.scandir

    def guarded(real: Any) -> Any:
        def call(path: Any = ".", *args: Any, **kwargs: Any) -> Any:
            if str(path).replace("/", "\\").startswith("\\\\"):
                raise AssertionError("a network path was touched")
            return real(path, *args, **kwargs)

        return call

    monkeypatch.setattr(os, "lstat", guarded(real_lstat))
    monkeypatch.setattr(os, "scandir", guarded(real_scandir))


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
        "\\\\\\pipe\\x",  # three leading separators
        "\\\\\\GLOBALROOT\\Device\\x",
        "\\\\?\\UNC\\\\.\\pipe\\x",  # an extended form that hides a device
        "\\\\.\\\\share",
        r"\\server\pipe\name",  # a remote named pipe is not a file share
        r"\\server\PIPE",
        r"\\server\Mailslot\x",
        r"\\server\DavWWWRoot\x",  # the WebDAV redirector
        r"\\server\davwwwroot",
        r"\\localhost\C$\Users",  # administrative, hidden and IPC shares
        r"\\server\ADMIN$",
        r"\\server\IPC$",
        "\\\\server\\share\\x\ud800",  # a lone surrogate
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


def test_names_are_folded_by_ascii_case_only(tmp_path: Path) -> None:
    roots = NetworkRoots(tmp_path)
    roots.add("\\\\s\\stra\u00dfe", now=NOW)

    assert roots.approves("\\\\S\\STRA\u00dfE\\a.jpg")
    assert not roots.approves("\\\\s\\strasse\\a.jpg")  # \u00df is not "ss" to NTFS
    assert not roots.approves("\\\\s\\STRA\u1e9eE\\a.jpg")


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

    with pytest.raises(NetworkRootsUnreadableError):
        roots.approved()
    assert not roots.approves(r"\\nas\family\a.jpg")


def test_a_file_cannot_widen_what_was_approved(tmp_path: Path) -> None:
    """The file is read through the same validation as an approval, so a hand-edited entry that
    would be refused if added (a device namespace) approves nothing."""
    (tmp_path / FILE_NAME).write_text(
        '{"roots": [{"path": "\\\\\\\\.\\\\pipe\\\\x", "approved_at": "t"}]}', encoding="utf-8"
    )

    roots = NetworkRoots(tmp_path)
    with pytest.raises(NetworkRootsUnreadableError):
        roots.approved()
    assert not roots.approves("\\\\.\\pipe\\x")


def test_concurrent_approvals_through_separate_instances_all_survive(tmp_path: Path) -> None:
    """The API builds one `NetworkRoots` per request, on threads: no approval may be lost."""
    names = [f"\\\\nas\\share{n}" for n in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda name: NetworkRoots(tmp_path).add(name, now=NOW), names))

    assert sorted(r.path for r in NetworkRoots(tmp_path).approved()) == sorted(names)
    assert not list(tmp_path.glob("*.partial"))


def test_an_unreadable_file_is_never_written_over(tmp_path: Path) -> None:
    kept = NetworkRoots(tmp_path).add("\\\\nas\\family", now=NOW)
    (tmp_path / FILE_NAME).write_text("{ damaged", encoding="utf-8")
    damaged = (tmp_path / FILE_NAME).read_bytes()

    roots = NetworkRoots(tmp_path)
    with pytest.raises(NetworkRootsUnreadableError):
        roots.add("\\\\nas\\work", now=NOW)
    with pytest.raises(NetworkRootsUnreadableError):
        roots.revoke(kept.id)
    with pytest.raises(NetworkRootsUnreadableError):
        roots.approved()

    assert (tmp_path / FILE_NAME).read_bytes() == damaged
    assert not roots.approves("\\\\nas\\family\\a.jpg")  # default deny meanwhile


def test_a_file_that_cannot_be_opened_is_unreadable_not_empty(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).mkdir()  # (a folder where the file should be)

    with pytest.raises(NetworkRootsUnreadableError):
        NetworkRoots(tmp_path).approved()


def test_an_approval_time_that_is_not_text_makes_the_file_untrusted(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_text(
        '{"roots": [{"path": "\\\\\\\\nas\\\\family", "approved_at": 5}]}', encoding="utf-8"
    )

    with pytest.raises(NetworkRootsUnreadableError):
        NetworkRoots(tmp_path).approved()


def test_a_duplicate_entry_in_the_file_is_listed_once(tmp_path: Path) -> None:
    entry = '{"path": "\\\\\\\\nas\\\\family", "approved_at": "t"}'
    (tmp_path / FILE_NAME).write_text(f'{{"roots": [{entry}, {entry}]}}', encoding="utf-8")

    assert len(NetworkRoots(tmp_path).approved()) == 1


def test_a_failed_write_leaves_the_old_file_and_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    NetworkRoots(tmp_path).add("\\\\nas\\family", now=NOW)
    before = (tmp_path / FILE_NAME).read_bytes()

    def refuse(*_: object) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        NetworkRoots(tmp_path).add("\\\\nas\\work", now=NOW)

    assert (tmp_path / FILE_NAME).read_bytes() == before
    assert not list(tmp_path.glob("*.partial"))
