"""A network share faked at the Win32 boundary (issue #174).

No SMB share can be created here without administrator rights, so a share `\\\\srv\\share` is a
folder on this disk and the one function that would contact the host (`local_path._nt_create` with
an absolute `\\??\\UNC\\...` name) is replaced: it records the contact and opens the folder instead.
Everything after the first step (relative opens, no-follow, the attribute and file type checks, the
handle) is the real thing. A host that is not the fake's is "offline": the open raises.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.infrastructure.storage import local_path

HOST = "srv"
SHARE = "share"
UNC = rf"\\{HOST}\{SHARE}"
ROOT_OPEN = "\\".join(["", "??", "UNC", HOST, SHARE, ""])  # what contacting the share looks like


@dataclass
class FakeShare:
    folder: Path  # what `\\srv\share` is on this disk
    contacts: list[str] = field(default_factory=list)  # every absolute `\??\UNC\...` open

    def path(self, *parts: str) -> str:
        return "\\".join([UNC, *parts])


def install(monkeypatch: pytest.MonkeyPatch, folder: Path) -> FakeShare:
    folder.mkdir(parents=True, exist_ok=True)
    share = FakeShare(folder)
    real_create = local_path._nt_create
    real_final = local_path._final_path

    def create(parent: int | None, name: str, *, directory: bool) -> int:
        if parent is None and name.upper().startswith("\\??\\UNC\\"):
            share.contacts.append(name)
            if name.upper() != f"\\??\\UNC\\{HOST}\\{SHARE}\\".upper():
                raise OSError(53, "The network path was not found")  # offline or unknown host
            return real_create(None, f"\\??\\{share.folder}\\", directory=True)
        return real_create(parent, name, directory=directory)

    def final(descriptor: int, flags: int) -> str | None:
        text = real_final(descriptor, flags)
        if flags != 0 or text is None:
            return text
        local = text.removeprefix("\\\\?\\")
        prefix = os.fspath(share.folder)
        if local.upper().startswith(prefix.upper()):
            return "\\\\?\\UNC\\" + f"{HOST}\\{SHARE}" + local[len(prefix) :]
        return text

    monkeypatch.setattr(local_path, "_nt_create", create)
    monkeypatch.setattr(local_path, "_final_path", final)
    return share
