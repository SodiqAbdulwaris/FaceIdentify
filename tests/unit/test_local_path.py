"""Where a path really leads, decided without going there (issue #174).

Real links and junctions on the real filesystem; the network targets are never contacted (the
`.invalid` host name cannot resolve, and the `probes` guard fails any call that follows a path, so
a refusal is shown to come before every probe or open).
"""

import os
from pathlib import Path
from typing import Any

import pytest

from backend.infrastructure.storage import local_path
from backend.infrastructure.storage.local_path import (
    DosDevice,
    Reparse,
    classify_dos_device,
    classify_reparse,
    is_device_component,
    local_target,
    open_local,
)
from tests.fixtures.links import link_directory

SHARE = r"\\faceidentify-test.invalid\share"
REPARSE = 0x400
RECALL_ON_DATA_ACCESS = 0x400000
RECALL_ON_OPEN = 0x40000
OFFLINE = 0x1000


class Followed(Exception):
    """Something looked at, or opened, what a path leads to."""


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail on every call that follows a path (stat, lstat, open, listing); record each entry
    looked at by name (`_entry`, which reads only the entry itself), so a test can say which."""
    looked: list[str] = []
    real_entry = local_path._entry

    def entry(path: Path) -> tuple[int, int] | None:
        looked.append(os.fspath(path))
        return real_entry(path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise Followed(args)

    monkeypatch.setattr(local_path, "_entry", entry)
    for owner, name in (
        (os, "lstat"),
        (os, "stat"),
        (os, "open"),
        (os, "scandir"),
        (os, "listdir"),
        (os, "access"),
        (os.path, "exists"),
        (os.path, "isfile"),
        (os.path, "isdir"),
        (os.path, "realpath"),
        (Path, "stat"),
        (Path, "open"),
        (Path, "resolve"),
        (Path, "exists"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    return looked


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
def test_network_and_device_forms_are_refused_before_any_probe(
    path: str, probes: list[str]
) -> None:
    assert local_target(path) is None
    assert probes == []


@pytest.mark.parametrize(
    "path",
    [
        r"\\?\C:\NUL",  # normalisation turns this into \\.\NUL
        r"\\?\C:\dir\..\CON",
        r"C:\NUL",
        r"C:\nul.txt",
        r"C:\Con.tar.gz",
        r"C:\COM1",
        r"C:\com9.png",
        r"C:\LPT1",
        "C:\\COM\u00b9",  # superscript digits are reserved too
        "C:\\lpt\u00b2.txt",
        "C:\\COM\u00b3",
        r"C:\CONIN$",
        r"C:\conout$",
        r"C:\NUL.",  # trailing dot
        r"C:\NUL ",  # trailing space
        r"C:\NUL .txt",
        r"C:\NUL:stream",  # a colon
        r"C:\PRN\a.png",  # a folder with a reserved name
        r"C:\AUX.d\a.png",
        r"C:\a.png:hidden",  # an alternate data stream
        r"C:\a.png::$DATA",
    ],
)
def test_device_names_and_streams_are_refused_before_any_probe(
    path: str, probes: list[str]
) -> None:
    assert local_target(path) is None
    assert probes == []


@pytest.mark.parametrize("part", ["a.png", "console.png", "NULL", "COM10", "COM", "LPT0", "x.NUL"])
def test_ordinary_names_are_not_devices(part: str) -> None:
    assert not is_device_component(part)


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


def test_a_link_to_a_device_is_refused(tmp_path: Path) -> None:
    (tmp_path / "d.png").symlink_to("C:\\NUL")

    assert local_target(tmp_path / "d.png") is None


def test_a_relative_link_is_followed_from_where_it_is(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "up").symlink_to(Path("..") / "real", target_is_directory=True)

    assert local_target(tmp_path / "sub" / "up" / "a.png") == tmp_path / "real" / "a.png"


def test_a_link_loop_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")

    assert local_target(tmp_path / "a") is None


@pytest.mark.parametrize(
    ("attributes", "tag", "expected"),
    [
        (0x20, 0, Reparse.PLAIN),  # an ordinary file
        (0x10, 0, Reparse.PLAIN),  # an ordinary directory
        (REPARSE, 0xA000000C, Reparse.FOLLOW),  # symbolic link
        (REPARSE, 0xA0000003, Reparse.FOLLOW),  # mount point (junction)
        (REPARSE, 0x8000001B, Reparse.REFUSE),  # app execution alias
        (REPARSE, 0x80000021, Reparse.REFUSE),  # OneDrive (old)
        (REPARSE, 0x9000001A, Reparse.PLAIN),  # cloud file, on this disk
        (REPARSE, 0x9000701A, Reparse.PLAIN),  # a cloud variant, on this disk
        (REPARSE | RECALL_ON_DATA_ACCESS, 0x9000001A, Reparse.REFUSE),  # not on this disk
        (REPARSE | RECALL_ON_OPEN, 0x9000F01A, Reparse.REFUSE),
        (REPARSE | OFFLINE, 0x9000101A, Reparse.REFUSE),
        (REPARSE, 0x90000019, Reparse.REFUSE),  # near the cloud tags, not one
        (REPARSE, 0xA0000001, Reparse.REFUSE),  # something else with a name surrogate
        (REPARSE, 0, Reparse.REFUSE),  # a reparse point that says nothing
    ],
)
def test_reparse_points_are_classified_from_attributes_and_tag(
    attributes: int, tag: int, expected: Reparse
) -> None:
    assert classify_reparse(attributes, tag) is expected


def fake_entry(monkeypatch: pytest.MonkeyPatch, entry: Path, attributes: int, tag: int) -> None:
    """Make the lookup of `entry` answer as a reparse point of the given kind (none can be made
    here)."""
    real = local_path._entry

    def lookup(path: Path) -> tuple[int, int] | None:
        return (attributes, tag) if path == entry else real(path)

    monkeypatch.setattr(local_path, "_entry", lookup)


def test_an_app_execution_alias_is_refused_even_deep_in_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "apps").mkdir()
    fake_entry(monkeypatch, tmp_path / "apps", REPARSE, 0x8000001B)

    assert local_target(tmp_path / "apps") is None
    assert local_target(tmp_path / "apps" / "x.png") is None


def test_a_cloud_placeholder_is_plain_only_when_it_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    picture = tmp_path / "a.png"
    fake_entry(monkeypatch, picture, REPARSE, 0x9000001A)
    assert local_target(picture) == picture

    fake_entry(monkeypatch, picture, REPARSE | RECALL_ON_DATA_ACCESS, 0x9000001A)
    assert local_target(picture) is None


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("\\Device\\HarddiskVolume3", (DosDevice.LOCAL, "\\Device\\HarddiskVolume3")),
        ("\\device\\harddiskvolume12", (DosDevice.LOCAL, "\\device\\harddiskvolume12")),
        ("\\Device\\CdRom0", (DosDevice.LOCAL, "\\Device\\CdRom0")),
        ("\\??\\C:\\base", (DosDevice.ALIAS, "C:\\base")),
        ("\\??\\D:\\", (DosDevice.ALIAS, "D:\\")),
        ("\\??\\UNC\\server\\share", (DosDevice.REFUSE, "")),
        ("\\??\\Volume{00000000-0000-0000-0000-000000000000}\\", (DosDevice.REFUSE, "")),
        ("\\Device\\LanmanRedirector\\;Z:0000\\server\\share", (DosDevice.REFUSE, "")),
        ("\\Device\\Mup\\server\\share", (DosDevice.REFUSE, "")),
        ("\\Device\\WebDavRedirector\\;Z:0\\host\\dav", (DosDevice.REFUSE, "")),
        ("", (DosDevice.REFUSE, "")),
        (None, (DosDevice.REFUSE, "")),
    ],
)
def test_a_drive_letters_device_is_classified(
    device: str | None, expected: tuple[DosDevice, str]
) -> None:
    assert classify_dos_device(device) == expected


def drives(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str | None]) -> None:
    """Pretend some drive letters map to these DOS devices (the others are asked for real)."""
    real = local_path._query_dos_device
    monkeypatch.setattr(
        local_path,
        "_query_dos_device",
        lambda drive: mapping[drive] if drive in mapping else real(drive),
    )


@pytest.mark.parametrize(
    "device",
    [
        "\\Device\\LanmanRedirector\\;Z:0000000000012345\\faceidentify-test.invalid\\share",
        "\\Device\\Mup\\faceidentify-test.invalid\\share",
        "\\??\\UNC\\faceidentify-test.invalid\\share",
        None,
    ],
)
def test_a_mapped_network_drive_is_refused_before_any_probe(
    device: str | None, monkeypatch: pytest.MonkeyPatch, probes: list[str]
) -> None:
    drives(monkeypatch, {"Z:": device})

    assert local_target("Z:\\a\\b.png") is None
    assert local_target("Z:a.png") is None  # (relative to that drive's directory)
    assert probes == []


def test_a_path_with_no_drive_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "abspath", lambda p: "\\a.png")  # abspath left it driveless

    assert local_target("a.png") is None


def test_a_subst_drive_is_walked_through_its_hidden_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "sub").mkdir()
    drives(monkeypatch, {"X:": f"\\??\\{real}"})

    assert local_target("X:\\sub\\a.png") == real / "sub" / "a.png"
    assert local_target("X:\\") == real


def test_a_subst_drive_over_a_link_to_a_share_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "base").symlink_to(SHARE, target_is_directory=True)
    drives(monkeypatch, {"X:": f"\\??\\{tmp_path / 'base'}"})

    assert local_target("X:\\a.png") is None


def test_a_subst_drive_over_a_mapped_drive_is_refused_before_any_probe(
    monkeypatch: pytest.MonkeyPatch, probes: list[str]
) -> None:
    drives(
        monkeypatch,
        {
            "X:": "\\??\\Y:\\dir",
            "Y:": "\\Device\\LanmanRedirector\\;Y:0\\faceidentify-test.invalid\\share",
        },
    )

    assert local_target("X:\\a.png") is None
    assert probes == []


def test_a_subst_loop_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    drives(monkeypatch, {"X:": "\\??\\X:\\dir"})

    assert local_target("X:\\a.png") is None


def test_this_machines_own_drive_is_a_local_volume(tmp_path: Path) -> None:
    drive = Path(os.path.abspath(tmp_path)).drive

    assert classify_dos_device(local_path._query_dos_device(drive))[0] is DosDevice.LOCAL
    assert local_path._query_dos_device("") is None


def test_a_file_opens_once_windows_confirms_where_it_is(tmp_path: Path) -> None:
    picture = tmp_path / "a.png"
    picture.write_bytes(b"pixels")

    handle = open_local(picture)

    assert handle is not None
    with handle:
        assert handle.read() == b"pixels"


def test_a_refused_path_is_not_opened(probes: list[str]) -> None:
    assert open_local(SHARE + r"\a.png") is None
    assert open_local(r"\\?\C:\NUL") is None
    assert probes == []


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_local(tmp_path / "missing.png")


class Spy:
    """A stand-in for the opened file that notes it was closed (and has no `read` to call)."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.closed = False

    def fileno(self) -> int:
        return int(self.real.fileno())

    def close(self) -> None:
        self.closed = True
        self.real.close()


@pytest.mark.parametrize(
    "final",
    [
        None,  # Windows could not say
        "\\Device\\Mup\\faceidentify-test.invalid\\share\\a.png",  # it is on a share
        "\\Device\\HarddiskVolume999\\elsewhere\\a.png",  # a local volume, but not the target
        "\\Device\\LanmanRedirector\\;Z:0\\faceidentify-test.invalid\\share\\a.png",
    ],
)
def test_a_handle_that_is_not_the_resolved_file_is_closed_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final: str | None
) -> None:
    picture = tmp_path / "a.png"
    picture.write_bytes(b"pixels")
    opened: list[Spy] = []
    real_open = Path.open

    def spying_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        spy = Spy(real_open(self, *args, **kwargs))
        opened.append(spy)
        return spy

    monkeypatch.setattr(Path, "open", spying_open)
    monkeypatch.setattr(local_path, "_final_nt_path", lambda descriptor: final)

    assert open_local(picture) is None
    assert opened[0].closed


def test_a_file_swapped_for_a_link_after_the_check_is_not_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race: `local_target` saw a plain file; by the open it is a link to another file."""
    (tmp_path / "other.png").write_bytes(b"other")
    (tmp_path / "swapped.png").symlink_to(tmp_path / "other.png")
    monkeypatch.setattr(local_path, "local_target", lambda path: tmp_path / "swapped.png")

    assert open_local(tmp_path / "plain.png") is None


def test_a_handle_that_cannot_be_asked_about_is_refused() -> None:
    assert local_path._final_nt_path(-1) is None


def test_a_real_handles_nt_path_is_the_expected_one(tmp_path: Path) -> None:
    picture = tmp_path / "a.png"
    picture.write_bytes(b"x")

    with picture.open("rb") as handle:
        final = local_path._final_nt_path(handle.fileno())
    expected = local_path._expected_nt_path(picture)

    assert final is not None
    assert expected is not None
    assert final.upper() == expected.upper()


def test_a_path_on_no_local_volume_has_no_nt_name(monkeypatch: pytest.MonkeyPatch) -> None:
    drives(monkeypatch, {"Z:": "\\Device\\Mup\\x"})

    assert local_path._expected_nt_path(Path("Z:\\a.png")) is None


@pytest.mark.parametrize("part", ["*", "a?.png", "<a>", 'a"b', "a|b"])
def test_wildcards_and_invalid_characters_are_refused_before_any_probe(
    part: str, probes: list[str]
) -> None:
    assert is_device_component(part)
    assert local_target(r"C:\dir" + "\\" + part + r"\a.png") is None
    assert probes == []


def test_an_entry_that_cannot_be_examined_is_not_walked_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = local_path._entry
    asked: list[Path] = []

    def lookup(path: Path) -> tuple[int, int] | None:
        asked.append(path)
        if path == tmp_path / "locked":
            raise PermissionError(5, "Access is denied")
        return real(path)

    monkeypatch.setattr(local_path, "_entry", lookup)

    assert local_target(tmp_path / "locked" / "deeper" / "a.png") is None
    assert asked[-1] == tmp_path / "locked"  # nothing below it was looked at


def test_an_entry_is_read_without_following_it(tmp_path: Path) -> None:
    (tmp_path / "plain.png").write_bytes(b"x")
    (tmp_path / "gone").symlink_to(tmp_path / "missing", target_is_directory=True)
    link_directory(tmp_path / "junction", tmp_path)

    plain = local_path._entry(tmp_path / "plain.png")
    symlink = local_path._entry(tmp_path / "gone")  # dangling: following it would fail
    junction = local_path._entry(tmp_path / "junction")

    assert plain is not None
    assert classify_reparse(*plain) is Reparse.PLAIN
    assert symlink is not None
    assert classify_reparse(*symlink) is Reparse.FOLLOW
    assert junction is not None
    assert classify_reparse(*junction) is Reparse.FOLLOW
    assert local_path._entry(tmp_path / "nothing.png") is None
    assert local_path._entry(tmp_path / "plain.png" / "below") is None  # a file is no folder


def test_an_entry_the_lookup_rejects_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="WinError"):
        local_path._entry(tmp_path / ("a" * 300))  # a name no folder can hold
