"""UNC path text: components, comparison and what can never be a share (issue #174).

Pure text work: nothing here opens a path or contacts a host. `local_path` uses it to decide what a
network target is; `network_roots` uses it to store and compare approvals, so the two can never
disagree about what a UNC path is.
"""

_EXTENDED_UNC = "\\\\?\\UNC\\"
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
_RESERVED |= {f"{name}{digit}" for name in ("COM", "LPT") for digit in "123456789¹²³"}


def is_device_component(part: str) -> bool:
    """A name Windows reads as a device, a stream or a search pattern, whatever follows it
    (`nul.txt`, `NUL .`, `a:b`, `*`)."""
    if any(char in part for char in ':*?<>"|'):
        return True  # an alternate data stream (and `NUL:`), or a wildcard the lookup would expand
    base = part.rstrip(" .").split(".")[0].rstrip(" ")
    return base.upper() in _RESERVED


def unc_parts(text: str) -> tuple[str, ...] | None:
    """The components of a conventional UNC path (`server`, `share`, folders...), or None when the
    text is not one (a drive path, a device namespace, an empty part, a `..`, or a part Windows
    would read as something else). Pure: nothing is opened. The extended
    UNC form is the same path."""
    text = text.replace("/", "\\")
    if text.upper().startswith(_EXTENDED_UNC):
        text = "\\\\" + text[len(_EXTENDED_UNC) :]
    if not text.startswith("\\\\") or text[2:3] in ("\\", ".", "?", ""):
        return None  # (a third separator, `\\.\` and `\\?\` are device or namespace forms)
    parts = [part for part in text[2:].split("\\") if part not in ("", ".")]
    if len(parts) < 2 or any(_unsafe(part) for part in parts):
        return None
    if "@" in parts[0]:
        return None  # `server@SSL` and `server@8080` are WebDAV: an HTTP connection, not SMB
    if parts[1].upper() == "DAVWWWROOT" or parts[1].endswith("$"):
        return None  # the WebDAV redirector's name; administrative, hidden and IPC shares
    return tuple(parts)


def _unsafe(part: str) -> bool:
    return (
        part == ".."
        or part[-1] in " ."  # Windows drops them: two spellings of one name
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in part)
        or is_device_component(part)  # wildcards, a stream, a device name
    )


def _fold(part: str) -> str:
    """ASCII case only: NTFS folds more than `str.upper` in some places and less in others, so a
    non-ASCII name is compared exactly (it can under-approve, never over-approve)."""
    return "".join(char.upper() if char.isascii() else char for char in part)


def key_of(parts: tuple[str, ...]) -> str:
    return "\\".join(_fold(part) for part in parts)


def is_inside(parts: tuple[str, ...], root_key: str) -> bool:
    """Whether the path (as components) is the approved root or lies below it."""
    wanted = root_key.split("\\")
    return len(parts) >= len(wanted) and [_fold(p) for p in parts[: len(wanted)]] == wanted
