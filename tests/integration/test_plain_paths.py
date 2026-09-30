"""`is_plain_directory` and `is_plain_file`: real entries, never links, on the real filesystem.

Everything that deletes, moves or reads files it owns relies on these to avoid being redirected by a
link planted where a real entry should be (workspaces, storage usage, the USearch index).
"""

from pathlib import Path

from backend.infrastructure.storage.plain import is_plain_directory, is_plain_file
from tests.fixtures.links import link_directory


def test_a_real_directory_and_a_real_file(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    file = tmp_path / "file.txt"
    file.write_text("x")

    assert is_plain_directory(folder)
    assert not is_plain_file(folder)
    assert is_plain_file(file)
    assert not is_plain_directory(file)


def test_a_junction_is_neither(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("x")
    link = tmp_path / "link"
    link_directory(link, target)

    assert not is_plain_directory(link)
    assert not is_plain_file(link)
    assert is_plain_file(link / "inside.txt") is True  # the file itself, reached through the link


def test_an_entry_that_does_not_exist_is_neither(tmp_path: Path) -> None:
    assert not is_plain_directory(tmp_path / "absent")
    assert not is_plain_file(tmp_path / "absent")
    assert not is_plain_file(tmp_path / "absent" / "deeper")
