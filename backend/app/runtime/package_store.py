"""Installing runtime packages from a local directory: stage, verify, publish atomically, recover.

(IMPLEMENTATION_ARCHITECTURE.md section 12; M3 decision "headless runtime installer".)

A package is installed in four steps that never touch the published place until the last:

1. copy every declared file into a staging directory `<local state>/installation/<key>.<token>`,
   hashing the bytes that were actually copied (the check of the source beforehand is only a fast
   refusal; what is installed is what was verified while copying);
2. copy the manifest into it, byte for byte;
3. write the marker `.installed` last, holding the manifest's hash: a directory with a valid
   marker is complete, one without is not;
4. publish with one `os.replace` of the whole directory to `<local state>/runtime/packages/<key>`.

So a package is either absent or complete where anyone looks, and what a crash leaves behind is
decided from what is on disk: nothing relies on the interrupted process having written down that
it was interrupted. `recover` publishes a staging directory that is complete and removes every
other one. This layer knows nothing of the database; registering what is installed in the catalog
is a separate step.
"""

import hashlib
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.runtime.manifest import (
    ManifestError,
    PackageManifest,
    file_problems,
    incompatibilities,
    parse_manifest,
)
from backend.infrastructure.storage.layout import StorageRoots

MANIFEST_FILE = "manifest.json"
MARKER_FILE = ".installed"
CHUNK = 1024 * 1024


class PackageInstallError(Exception):
    """A package that cannot be installed. Nothing of it is left behind."""


class InvalidPackageError(PackageInstallError):
    """The source is not a package we can trust: no or bad manifest, or its files do not match."""


class IncompatiblePackageError(PackageInstallError):
    """The package is not for this machine."""


class PackageExistsError(PackageInstallError):
    """A different package has this key; installed bytes are never replaced."""


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    key: str
    version: str
    path: Path
    manifest: PackageManifest


@dataclass(slots=True)
class InstallRecoveryReport:
    published: list[str] = field(
        default_factory=list
    )  # a complete staging directory, now installed
    removed: list[str] = field(default_factory=list)  # an incomplete or superseded one, deleted
    left: list[str] = field(default_factory=list)  # something we could not or should not remove
    invalid: list[str] = field(default_factory=list)  # a published directory that is not complete


def _no_checkpoint(step: str) -> None:
    """The install steps announce themselves here so tests can stop the process after any one."""


def _sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RuntimePackageStore:
    def __init__(
        self,
        roots: StorageRoots,
        *,
        new_id: Callable[[], uuid.UUID],
        checkpoint: Callable[[str], None] = _no_checkpoint,
    ) -> None:
        self._published = roots.runtime_packages
        self._staging = roots.installation
        self._new_id = new_id
        self._checkpoint = checkpoint

    # --- reading ----------------------------------------------------------------------------

    def installed(self) -> list[InstalledPackage]:
        """The packages that are complete. A directory that is not never appears here."""
        if not self._published.is_dir():
            return []
        found = (self._read_complete(entry) for entry in sorted(self._published.iterdir()))
        return [p for p in found if p is not None and p.path.name == p.key]

    def get(self, key: str) -> InstalledPackage | None:
        return next((p for p in self.installed() if p.key == key), None)

    def verify(self, key: str) -> list[str]:
        """Re-check an installed package's bytes against its manifest (empty means intact)."""
        package = self.get(key)
        if package is None:
            return [f"{key}: not installed"]
        return file_problems(package.path, package.manifest)

    # --- installing -------------------------------------------------------------------------

    def install(self, source: Path, facts: Mapping[str, str]) -> InstalledPackage:
        """Install the package in the directory `source` (a `manifest.json` and its files).
        Installing what is already installed, byte for byte, changes nothing."""
        manifest_bytes = self._read_manifest(source)
        manifest = self._parse(manifest_bytes)
        problems = incompatibilities(manifest, facts)
        if problems:
            raise IncompatiblePackageError(f"{manifest.key}: " + "; ".join(problems))
        problems = file_problems(source, manifest)
        if problems:
            raise InvalidPackageError(f"{manifest.key}: " + "; ".join(problems))

        final = self._published / manifest.key
        if final.exists():
            return self._already_installed(final, manifest_bytes)

        stage = self._staging / f"{manifest.key}.{self._new_id().hex}"
        self._published.mkdir(parents=True, exist_ok=True)
        stage.mkdir(parents=True)
        self._checkpoint("staged")
        try:
            self._copy_verified(source, stage, manifest)
            (stage / MANIFEST_FILE).write_bytes(manifest_bytes)
            self._checkpoint("copied")
            self._write_marker(stage, manifest_bytes)
            self._checkpoint("marked")
            try:
                os.replace(stage, final)
            except OSError:
                if final.exists():  # another process published the same key first
                    shutil.rmtree(stage, ignore_errors=True)
                    return self._already_installed(final, manifest_bytes)
                raise
            self._checkpoint("published")
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        package = self._read_complete(final)
        assert package is not None  # we just published a marked directory
        return package

    def _already_installed(self, final: Path, manifest_bytes: bytes) -> InstalledPackage:
        package = self._read_complete(final)
        if package is None or _sha256_of(manifest_bytes) != _sha256_of(
            (final / MANIFEST_FILE).read_bytes()
        ):
            raise PackageExistsError(
                f"{final.name}: a different package is installed under this key"
            )
        return package

    @staticmethod
    def _read_manifest(source: Path) -> bytes:
        try:
            return (source / MANIFEST_FILE).read_bytes()
        except OSError as error:
            raise InvalidPackageError(
                f"no readable {MANIFEST_FILE} in the package: {error}"
            ) from error

    @staticmethod
    def _parse(manifest_bytes: bytes) -> PackageManifest:
        try:
            return parse_manifest(manifest_bytes)
        except ManifestError as error:
            raise InvalidPackageError(f"manifest refused: {error}") from error

    @staticmethod
    def _copy_verified(source: Path, stage: Path, manifest: PackageManifest) -> None:
        """Copy each declared file, hashing what is written: the installed bytes are the ones
        verified, whatever happened to the source since it was first looked at."""
        for export in manifest.exports:
            target = stage / export.file
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with (source / export.file).open("rb") as reader, target.open("xb") as writer:
                while chunk := reader.read(CHUNK):
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if digest.digest() != export.sha256:
                raise InvalidPackageError(f"{export.file}: changed while it was being installed")

    @staticmethod
    def _write_marker(stage: Path, manifest_bytes: bytes) -> None:
        with (stage / MARKER_FILE).open("wb") as marker:
            marker.write(_sha256_of(manifest_bytes).encode("ascii"))
            marker.flush()
            os.fsync(marker.fileno())

    # --- what a directory is ----------------------------------------------------------------

    def _read_complete(self, directory: Path) -> InstalledPackage | None:
        """The package a directory holds if it is complete: a marker whose hash is that of the
        manifest beside it, and a manifest that parses. Otherwise None."""
        try:
            marker = (directory / MARKER_FILE).read_bytes()
            manifest_bytes = (directory / MANIFEST_FILE).read_bytes()
        except OSError:
            return None
        if marker != _sha256_of(manifest_bytes).encode("ascii"):
            return None
        try:
            manifest = parse_manifest(manifest_bytes)
        except ManifestError:
            return None
        return InstalledPackage(manifest.key, manifest.version, directory, manifest)

    # --- recovery ---------------------------------------------------------------------------

    def recover(self) -> InstallRecoveryReport:
        """Settle what an interrupted install left behind, from what is on disk. A complete
        staging directory is published (its marker was the last thing written, so the copy is
        whole); every other staging directory is removed; a published directory that is not
        complete is reported and left alone. Idempotent, and one stuck directory does not stop
        the rest."""
        report = InstallRecoveryReport()
        if self._staging.is_dir():
            for entry in sorted(self._staging.iterdir()):
                self._settle(entry, report)
        if self._published.is_dir():
            for entry in sorted(self._published.iterdir()):
                package = self._read_complete(entry)
                if package is None or package.key != entry.name:
                    report.invalid.append(entry.name)
        return report

    def _settle(self, entry: Path, report: InstallRecoveryReport) -> None:
        key = entry.name.rpartition(".")[0]
        package = self._read_complete(entry)
        final = self._published / key
        if package is not None and package.key == key and not final.exists():
            try:
                self._published.mkdir(parents=True, exist_ok=True)
                os.replace(entry, final)
            except OSError:
                report.left.append(entry.name)
            else:
                report.published.append(key)
            return
        try:
            shutil.rmtree(entry)
        except OSError:
            report.left.append(entry.name)
        else:
            report.removed.append(entry.name)
