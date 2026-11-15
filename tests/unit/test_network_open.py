"""Reading an approved network target, and nothing else (issue #174, PR B).

The share is faked at the Win32 boundary (`tests/fixtures/fake_share.py`): no real share can be
made without administrator rights, so what is *not* exercised here is SMB itself. Everything the
policy decides is, with real files, real links and junctions, and the real no-follow handle walk.
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.infrastructure.storage import local_path
from backend.infrastructure.storage.local_path import local_target, open_local
from tests.fixtures.fake_share import HOST, SHARE, UNC, FakeShare, install
from tests.fixtures.links import link_directory

PIXELS = b"pixels"
MAPPED = r"\Device\Mup\;LanmanRedirector\;Z:0000000000012345" + rf"\{HOST}\{SHARE}"


@pytest.fixture
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeShare:
    fake = install(monkeypatch, tmp_path / "the-share")
    (fake.folder / "a.png").write_bytes(PIXELS)
    (fake.folder / "sub").mkdir()
    (fake.folder / "sub" / "b.png").write_bytes(b"deep")
    return fake


def approving(*roots: str):  # type: ignore[no-untyped-def]
    from backend.infrastructure.storage.unc import is_inside, key_of, unc_parts

    keys = [key_of(unc_parts(root) or ()) for root in roots]

    def approved(path: str) -> bool:
        parts = unc_parts(path)
        return parts is not None and any(is_inside(parts, key) for key in keys)

    return approved


def drives(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str | None]) -> None:
    real = local_path._query_dos_device
    monkeypatch.setattr(
        local_path, "_query_dos_device", lambda d: mapping[d] if d in mapping else real(d)
    )


def read(path: str | Path, approved: object) -> bytes | None:
    handle = open_local(path, approved)  # type: ignore[arg-type]
    if handle is None:
        return None
    with handle:
        return handle.read()


def test_an_approved_share_is_read(share: FakeShare) -> None:
    assert read(share.path("a.png"), approving(UNC)) == PIXELS
    assert share.contacts == [f"\\??\\UNC\\{HOST}\\{SHARE}\\"]


def test_a_folder_root_covers_what_is_in_it_and_nothing_beside_it(share: FakeShare) -> None:
    approved = approving(share.path("sub"))

    assert read(share.path("sub", "b.png"), approved) == b"deep"
    assert read(share.path("a.png"), approved) is None  # in the share, outside the root


@pytest.mark.parametrize(
    "spelling",
    [
        "//SRV/Share/A.PNG",
        r"\\?\UNC\srv\share\a.png",
        r"\\?\unc\SRV\SHARE\a.png",
        r"\\srv\share\\a.png",
        r"\\srv\share\.\a.png",
    ],
)
def test_the_same_picture_by_another_spelling_is_the_same_decision(
    share: FakeShare, spelling: str
) -> None:
    assert read(spelling, approving(UNC)) == PIXELS


@pytest.mark.parametrize(
    "path",
    [
        r"\\other\share\a.png",  # another host
        r"\\srv\share2\a.png",  # a longer share name is not the approved one
        r"\\srv\sha\a.png",
        r"\\srv\share\..\other\a.png",  # a dot-dot never leaves the approved share unnoticed
        r"\\srv\ADMIN$\a.png",
        r"\\srv\DavWWWRoot\a.png",
        r"\\srv\pipe\a.png",
        r"\\srv\MAILSLOT\a.png",
        r"\\.\pipe\srv",
        r"\\?\GLOBALROOT\Device\x",
        r"\\?\UNC\\.\pipe\x",
        r"\\\srv\share\a.png",
        "\\\\srv\\share\\a.png\x00",
    ],
)
def test_what_is_not_approved_is_refused_before_any_contact(share: FakeShare, path: str) -> None:
    assert local_target(path, approving(UNC)) is None
    assert read(path, approving(UNC)) is None
    assert share.contacts == []


def test_without_an_approval_nothing_on_a_network_is_read_or_contacted(share: FakeShare) -> None:
    assert read(share.path("a.png"), None) is None
    assert read(share.path("a.png"), approving()) is None
    assert share.contacts == []


def test_a_mapped_drive_is_the_share_it_maps(
    share: FakeShare, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives(monkeypatch, {"Z:": MAPPED})

    assert read("Z:\\a.png", approving(UNC)) == PIXELS
    assert read("Z:\\sub\\b.png", approving(share.path("sub"))) == b"deep"
    assert local_target("Z:\\a.png", approving(UNC)) == Path(UNC + "\\a.png")


def test_a_mapped_drive_is_judged_by_the_share_not_the_letter(
    share: FakeShare, monkeypatch: pytest.MonkeyPatch
) -> None:
    drives(monkeypatch, {"Z:": MAPPED.replace(HOST, "elsewhere")})

    assert read("Z:\\a.png", approving(UNC)) is None
    assert share.contacts == []


@pytest.mark.parametrize(
    "device",
    [
        "\\Device\\Mup\\srv\\share",  # no protocol named: could be DFS
        r"\Device\WebDavRedirector\;Z:0\srv\share",
        r"\Device\Mup\;RdpDr\;Z:0\srv\share",
        None,
    ],
)
def test_a_mapping_that_is_not_plainly_smb_is_refused(
    share: FakeShare, monkeypatch: pytest.MonkeyPatch, device: str | None
) -> None:
    drives(monkeypatch, {"Z:": device})

    assert read("Z:\\a.png", approving(UNC)) is None
    assert share.contacts == []


def test_a_subst_of_a_share_is_the_share(share: FakeShare, monkeypatch: pytest.MonkeyPatch) -> None:
    drives(monkeypatch, {"X:": f"\\??\\UNC\\{HOST}\\{SHARE}"})

    assert read("X:\\a.png", approving(UNC)) == PIXELS
    assert read("X:\\a.png", approving()) is None


def test_a_link_to_an_approved_share_is_followed_and_to_another_is_not(
    share: FakeShare, tmp_path: Path
) -> None:
    (tmp_path / "ok.png").symlink_to(share.path("a.png"))
    (tmp_path / "no.png").symlink_to(r"\\other\share\a.png")
    (tmp_path / "dir").symlink_to(UNC, target_is_directory=True)

    assert read(tmp_path / "ok.png", approving(UNC)) == PIXELS
    assert read(tmp_path / "dir" / "sub" / "b.png", approving(UNC)) == b"deep"
    assert read(tmp_path / "no.png", approving(UNC)) is None
    assert read(tmp_path / "ok.png", approving()) is None
    assert share.contacts == [f"\\??\\UNC\\{HOST}\\{SHARE}\\"] * 2  # only the two that were read


def test_nested_links_are_decided_by_where_the_last_one_leads(
    share: FakeShare, tmp_path: Path
) -> None:
    (tmp_path / "far").symlink_to(UNC, target_is_directory=True)
    link_directory(tmp_path / "near", tmp_path)  # a junction to the folder holding the links
    (tmp_path / "hop").symlink_to(tmp_path / "near" / "far" / "sub", target_is_directory=True)
    (tmp_path / "bad").symlink_to(tmp_path / "hop" / ".." / "sub", target_is_directory=True)

    assert read(tmp_path / "hop" / "b.png", approving(UNC)) == b"deep"
    assert read(tmp_path / "hop" / "b.png", approving(share.path("sub"))) == b"deep"
    assert read(tmp_path / "hop" / "b.png", approving(r"\\srv\elsewhere")) is None
    assert local_target(tmp_path / "bad" / "b.png", approving(UNC)) is not None  # (just resolves)


def test_a_link_that_leaves_the_share_is_not_followed_by_the_walk(
    share: FakeShare, tmp_path: Path
) -> None:
    """A link *on the share* is never walked through: the open refuses a reparse point, so a
    server-side link cannot send the read to another place, approved or not."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"secret")
    (share.folder / "out").symlink_to(outside, target_is_directory=True)
    (share.folder / "leak.png").symlink_to(outside / "secret.png")

    assert read(share.path("out", "secret.png"), approving(UNC)) is None
    assert read(share.path("leak.png"), approving(UNC)) is None


def test_a_folder_a_missing_file_and_a_device_are_not_pictures(
    share: FakeShare, tmp_path: Path
) -> None:
    with pytest.raises(IsADirectoryError):  # a folder
        read(share.path("sub"), approving(UNC))
    with pytest.raises(FileNotFoundError):
        read(share.path("missing.png"), approving(UNC))
    assert read(share.path("NUL"), approving(UNC)) is None
    assert read(UNC, approving(UNC)) is None  # the share itself


def test_a_local_folder_is_not_a_picture(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        read(tmp_path, None)


def test_a_file_that_leads_somewhere_else_than_approved_is_closed_unread(
    share: FakeShare, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handle's own final name is the last check: a share that answers with a different
    place (a server-side redirect, DFS) is not read, even if the text was approved."""
    monkeypatch.setattr(local_path, "_final_unc_path", lambda d: r"\\srv\elsewhere\a.png")
    closed: list[bool] = []
    real_as_file = local_path._as_file

    def spying(handle: int) -> object:
        opened = real_as_file(handle)
        original = opened.close

        def close() -> None:
            closed.append(True)
            original()

        opened.close = close  # type: ignore[method-assign]
        return opened

    monkeypatch.setattr(local_path, "_as_file", spying)

    assert read(share.path("a.png"), approving(UNC)) is None
    assert closed == [True]
    monkeypatch.setattr(local_path, "_final_unc_path", lambda d: None)
    assert read(share.path("a.png"), approving(UNC)) is None


def test_an_offline_share_fails_to_open_and_can_be_tried_again(
    share: FakeShare, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = approving(r"\\gone\share", UNC)

    with pytest.raises(OSError, match="not found"):
        read(r"\\gone\share\a.png", approved)
    assert read(share.path("a.png"), approved) == PIXELS  # nothing was left holding
    assert share.contacts == ["\\??\\UNC\\gone\\share\\", f"\\??\\UNC\\{HOST}\\{SHARE}\\"]


def swap_when_opening(
    monkeypatch: pytest.MonkeyPatch, name: str, swap: Callable[[], None], *, after: bool = False
) -> None:
    """Run `swap` once, just before (or, with `after`, just after) the step named `name` is opened:
    the moment a planted link would matter, between one step of the walk and the next."""
    real = local_path._nt_create
    done: list[bool] = []

    def create(parent: int | None, step: str) -> int:
        fire = step == name and parent is not None and not done
        if fire and not after:
            done.append(True)
            swap()
        handle = real(parent, step)
        if fire and after:
            done.append(True)
            swap()
        return handle

    monkeypatch.setattr(local_path, "_nt_create", create)


def test_a_directory_swapped_for_a_link_to_an_unapproved_share_is_never_contacted(
    share: FakeShare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race of the first version, aimed at a share nobody approved: between one step of the
    walk and the next, `plain` becomes a link to it. Every step is opened without following, so the
    link is read, judged by where it leads and refused: nothing reaches out, even to look."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.png").write_bytes(b"checked")

    def swap() -> None:
        (plain / "a.png").unlink()
        plain.rmdir()
        plain.symlink_to(r"\\other\share", target_is_directory=True)

    swap_when_opening(monkeypatch, "plain", swap)

    assert read(plain / "a.png", approving(UNC)) is None
    assert share.contacts == []


def test_a_directory_swapped_for_a_link_is_judged_by_where_the_link_now_leads(
    share: FakeShare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.png").write_bytes(b"checked")
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.png").write_bytes(b"other")

    def swap() -> None:
        (plain / "a.png").unlink()
        plain.rmdir()
        link_directory(plain, other)

    swap_when_opening(monkeypatch, "plain", swap)

    assert read(plain / "a.png", None) == b"other"  # the resolved target, wherever it is now


def test_a_directory_swapped_for_a_link_to_an_approved_share_is_read_from_the_share(
    share: FakeShare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.png").write_bytes(b"checked")

    def swap() -> None:
        (plain / "a.png").unlink()
        plain.rmdir()
        plain.symlink_to(UNC, target_is_directory=True)

    swap_when_opening(monkeypatch, "plain", swap)

    assert read(plain / "a.png", approving(UNC)) == PIXELS  # the share's a.png, by the policy


def test_a_directory_replaced_after_it_was_opened_is_caught_by_the_final_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step that was opened is the real directory; if the name is then pointed elsewhere the
    handle's own final name no longer matches the target and nothing is read."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.png").write_bytes(b"checked")
    other = tmp_path / "other"
    other.mkdir()

    def swap() -> None:
        plain.rename(tmp_path / "moved")
        link_directory(plain, other)

    swap_when_opening(monkeypatch, "plain", swap, after=True)

    assert read(plain / "a.png", None) is None


def test_a_drive_letter_remapped_after_the_check_is_not_followed(
    share: FakeShare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk is opened by the device the letter was checked against; if the letter is then
    mapped to a share, the final-name check no longer finds a local volume and nothing is read."""
    picture = tmp_path / "a.png"
    picture.write_bytes(b"local")
    drive = picture.drive
    real = local_path._query_dos_device
    asked: list[str] = []

    def remapped(letter: str) -> str | None:
        asked.append(letter)
        return MAPPED if letter == drive and len(asked) > 1 else real(letter)

    monkeypatch.setattr(local_path, "_query_dos_device", remapped)

    assert read(picture, approving(UNC)) is None
    assert share.contacts == []


def test_a_plain_local_file_and_a_junction_to_a_local_folder_still_read(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.png").write_bytes(PIXELS)
    link_directory(tmp_path / "via", tmp_path / "real")

    assert read(tmp_path / "real" / "a.png", None) == PIXELS
    assert read(tmp_path / "via" / "a.png", None) == PIXELS
    assert os.path.exists(tmp_path / "real" / "a.png")


def test_a_volume_root_and_a_path_with_no_file_are_refused(tmp_path: Path) -> None:
    assert read(Path(tmp_path.anchor), None) is None


def test_a_handle_that_cannot_be_asked_about_has_no_attributes() -> None:
    assert local_path._attributes(0) is None


def test_a_handle_that_cannot_become_a_file_is_closed_and_raises() -> None:
    with pytest.raises(OSError, match="Bad file descriptor|Invalid handle|WinError"):
        local_path._as_file(-1)


def test_an_entry_that_cannot_be_examined_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.png").write_bytes(PIXELS)
    monkeypatch.setattr(local_path, "_attributes", lambda handle: None)

    assert read(tmp_path / "a.png", None) is None
