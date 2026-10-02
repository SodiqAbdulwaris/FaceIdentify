"""The runtime package manifest: declarative, versioned, validated before anything is installed
(IMPLEMENTATION_ARCHITECTURE.md section 12; M3 decision "headless runtime installer").

A manifest says what a package contains (components, the model exports with their hashes, the
runtime variants that execute them) and which machines it is for. It is data, never logic:
installation behaviour lives in application code. Parsing is strict (exact keys, exact types,
no duplicate keys, no unsafe file paths) because a manifest comes from outside the library.
"""

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from backend.infrastructure.storage.files import digest_path

SCHEMA_VERSION = 1
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


class ManifestError(ValueError):
    """The manifest is not acceptable. The message says which part and why."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the bytes came from and under what terms. Recorded, never inferred: weights whose
    redistribution is unclear must say so (`redistributable` false) rather than be omitted."""

    license: str
    source: str
    redistributable: bool


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    key: str
    kind: str
    version: str
    contract: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ExportSpec:
    component: str  # the key of a ComponentSpec
    file: str  # relative path inside the package, forward slashes
    format: str
    precision: str
    sha256: bytes
    size_bytes: int
    input_contract: Mapping[str, Any]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class VariantSpec:
    export_file: str  # the `file` of an ExportSpec
    provider: str
    device_kind: str
    variant_key: str
    requirements: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PackageManifest:
    key: str
    version: str
    requirements: Mapping[str, tuple[str, ...]]  # fact name -> the values this package accepts
    components: tuple[ComponentSpec, ...]
    exports: tuple[ExportSpec, ...]
    variants: tuple[VariantSpec, ...]
    schema_version: int = SCHEMA_VERSION


# --- strict readers ------------------------------------------------------------------------------


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _refuse_constant(name: str) -> Any:
    raise ManifestError(f"{name} is not valid JSON")


def _obj(value: Any, what: str, required: set[str]) -> Any:
    if not isinstance(value, dict):
        raise ManifestError(f"{what} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required
    if missing or extra:
        raise ManifestError(f"{what}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return value


def _str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ManifestError(f"{what} must be a non-empty string without surrounding spaces")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ManifestError(f"{what} contains a control or invisible character")
    return value


def _list(value: Any, what: str, *, non_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (non_empty and not value):
        raise ManifestError(f"{what} must be {'a non-empty list' if non_empty else 'a list'}")
    return value


def _dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{what} must be an object")
    return value


def safe_relative_path(value: Any, what: str = "file") -> str:
    """A package-relative path with forward slashes that cannot leave the package on any platform:
    no empty, `.` or `..` segment, no drive, backslash or control character, nothing Windows
    would rewrite (trailing dot or space, reserved device names)."""
    path = _str(value, what)
    if "\\" in path or ":" in path:
        raise ManifestError(f"{what} {path!r} is not a safe relative path")
    for segment in path.split("/"):
        stem = segment.split(".")[0].lower()
        if (
            segment in ("", ".", "..")
            or segment != segment.rstrip(". ")
            or stem in _WINDOWS_RESERVED
        ):
            raise ManifestError(f"{what} {path!r} is not a safe relative path")
    return path


# --- parsing -------------------------------------------------------------------------------------


def parse_manifest(text: str | bytes) -> PackageManifest:
    """Read and validate a manifest. Every cross-reference must resolve and every name must be
    unique, so a manifest that parses can be installed without further interpretation."""
    try:
        raw = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_refuse_constant)
    except json.JSONDecodeError as error:
        raise ManifestError(f"not valid JSON: {error.msg}") from error
    except UnicodeDecodeError as error:
        raise ManifestError("not valid UTF-8 text") from error
    except RecursionError:
        raise ManifestError("nested too deeply") from None
    data = _obj(
        raw,
        "manifest",
        {"schema_version", "key", "version", "requirements", "components", "exports", "variants"},
    )
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ManifestError(f"manifest schema version {version!r} is not supported")

    requirements: dict[str, tuple[str, ...]] = {}
    for name, allowed in _dict(data["requirements"], "requirements").items():
        values = tuple(
            _str(v, f"requirements.{name}") for v in _list(allowed, name, non_empty=True)
        )
        requirements[_str(name, "requirement name")] = values

    components = tuple(
        _component(c) for c in _list(data["components"], "components", non_empty=True)
    )
    _unique([c.key for c in components], "component key")
    exports = tuple(_export(e) for e in _list(data["exports"], "exports", non_empty=True))
    _unique([e.file.lower() for e in exports], "export file")  # case-insensitive: Windows
    component_keys = {c.key for c in components}
    for export in exports:
        if export.component not in component_keys:
            raise ManifestError(
                f"export {export.file!r} names unknown component {export.component!r}"
            )
    variants = tuple(_variant(v) for v in _list(data["variants"], "variants", non_empty=True))
    _unique([v.variant_key for v in variants], "variant key")
    spelling = {e.file.lower(): e.file for e in exports}
    resolved: list[VariantSpec] = []
    for variant in variants:
        file = spelling.get(variant.export_file.lower())
        if file is None:
            raise ManifestError(f"variant {variant.variant_key!r} names unknown export file")
        resolved.append(replace(variant, export_file=file))
    variants = tuple(resolved)
    return PackageManifest(
        key=_str(data["key"], "key"),
        version=_str(data["version"], "version"),
        requirements=requirements,
        components=components,
        exports=exports,
        variants=variants,
    )


def _unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ManifestError(f"duplicate {what} {value!r}")
        seen.add(value)


def _component(value: Any) -> ComponentSpec:
    data = _obj(value, "component", {"key", "kind", "version", "contract"})
    return ComponentSpec(
        key=_str(data["key"], "component key"),
        kind=_str(data["kind"], "component kind"),
        version=_str(data["version"], "component version"),
        contract=_dict(data["contract"], "component contract"),
    )


def _export(value: Any) -> ExportSpec:
    data = _obj(
        value,
        "export",
        {
            "component",
            "file",
            "format",
            "precision",
            "sha256",
            "size_bytes",
            "input_contract",
            "provenance",
        },
    )
    digest = _str(data["sha256"], "sha256")
    if not _SHA256_HEX.match(digest):
        raise ManifestError("sha256 must be 64 lowercase hexadecimal characters")
    size = data["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ManifestError("size_bytes must be a non-negative integer")
    provenance = _obj(data["provenance"], "provenance", {"license", "source", "redistributable"})
    if not isinstance(provenance["redistributable"], bool):
        raise ManifestError("redistributable must be true or false")
    return ExportSpec(
        component=_str(data["component"], "export component"),
        file=safe_relative_path(data["file"], "export file"),
        format=_str(data["format"], "format"),
        precision=_str(data["precision"], "precision"),
        sha256=bytes.fromhex(digest),
        size_bytes=size,
        input_contract=_dict(data["input_contract"], "input_contract"),
        provenance=Provenance(
            license=_str(provenance["license"], "license"),
            source=_str(provenance["source"], "source"),
            redistributable=provenance["redistributable"],
        ),
    )


def _variant(value: Any) -> VariantSpec:
    data = _obj(
        value, "variant", {"export_file", "provider", "device_kind", "variant_key", "requirements"}
    )
    return VariantSpec(
        export_file=safe_relative_path(data["export_file"], "variant export_file"),
        provider=_str(data["provider"], "provider"),
        device_kind=_str(data["device_kind"], "device_kind"),
        variant_key=_str(data["variant_key"], "variant_key"),
        requirements=_dict(data["requirements"], "variant requirements"),
    )


# --- compatibility and integrity -----------------------------------------------------------------


def incompatibilities(manifest: PackageManifest, facts: Mapping[str, str]) -> list[str]:
    """Why this package is not for this machine; empty means compatible. Every requirement the
    package makes must be matched by a known fact (names and values compared case-insensitively):
    an unknown fact is a mismatch, never assumed to be fine."""
    known = {name.lower(): value for name, value in facts.items()}
    problems: list[str] = []
    for name, allowed in manifest.requirements.items():
        actual = known.get(name.lower())
        if actual is None:
            problems.append(
                f"{name} is not known on this machine (package needs {', '.join(allowed)})"
            )
        elif str(actual).lower() not in {a.lower() for a in allowed}:
            problems.append(f"{name} is {actual!r}, package needs {', '.join(allowed)}")
    return problems


def file_problems(root: Path, manifest: PackageManifest) -> list[str]:
    """Check every declared file in the package directory `root`: present, a regular file inside
    `root` (a symlink out of it is refused), the declared size, the declared hash. Files that are
    not declared are not part of the package and are ignored. An empty result does not bind the
    check to a later copy: whatever copies these files must verify what it copied."""
    problems: list[str] = []
    base = root.resolve()
    for export in manifest.exports:
        path = root / export.file
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):  # a link loop, or a path the system cannot resolve
            problems.append(f"{export.file}: cannot be resolved")
            continue
        if base != resolved and base not in resolved.parents:
            problems.append(f"{export.file}: resolves outside the package")
        elif not path.is_file():
            problems.append(f"{export.file}: missing")
        else:
            stored = digest_path(path)
            if stored.size_bytes != export.size_bytes:
                problems.append(
                    f"{export.file}: size {stored.size_bytes}, manifest says {export.size_bytes}"
                )
            elif stored.sha256 != export.sha256:
                problems.append(f"{export.file}: hash does not match the manifest")
    return problems
