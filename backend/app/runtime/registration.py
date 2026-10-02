"""Registering an installed runtime package in the library's catalog (issue 80;
PERSISTENCE_IMPLEMENTATION.md section 18; ML_COMPONENTS_AND_EVALUATION.md sections 9.1 and 18.1).

The installer (`package_store`) puts a package on this machine; the library has to know what it is
so that observations and representations can say which components made them, and so that the
representation space a vector belongs to is a recorded identity and not an assumption. Registration
turns an installed package's manifest into catalog rows, in the caller's transaction (it flushes,
it never commits):

* `Component`, `ComponentVersion`, `ModelExport` and `RuntimeVariant` rows, each found by its
  identity or created. Catalog rows are immutable (section 18), so a row that exists with
  different content is an error, never an update; two packages that ship the same component
  version and the same weights (a CPU package and a CUDA package, say) share those rows;
* a `REFERENCED` artifact for each export's file and for the package's manifest file (a regular
  file, which is what startup checks; the bytes stay
  machine-local in the package, never in the library: Architecture 12.2), and the installation
  records that point at them; a library moved to another machine finds them `MISSING` and says so,
  it never substitutes another package;
* for every export of a `FACE_REPRESENTATION` component, one `RepresentationSpace`, whose identity
  is what the owner decided (ML 18.1): the model family, the weights digest, the dimensionality,
  the preprocessing contract version, the normalisation and its contract version, and the model
  compatibility version, and **not** the execution provider; its `semantic_key` is the SHA-256
  fingerprint of that record, so equal identities are one space and anything else is another. The
  weights digest is the export file's SHA-256: every export is one complete weight artifact, so two
  exports of one model (two precisions) are two spaces. A model with several weight artifacts needs
  the aggregate scheme ML 18.1 leaves undefined; the manifest cannot express it yet, so it is not
  invented here;
* for every variant of such an export, a compatibility row to its space in the state `DECLARED`:
  the manifest says the variant runs that export, which is a claim; numerical equivalence of
  another provider is validated later and moves it on.

What a component's manifest `contract` must say (this is the agent's convention for the two
reference kinds, validated here): a `FACE_DETECTOR` names its `preprocessing_contract`; a
`FACE_REPRESENTATION` names `family`, `dimension`, `preprocessing_contract`, `normalization`,
`normalization_contract_version` and `compatibility_version`.

Registering the same package again (same key, same manifest, same place) finds what it made and
returns the same ids; a different manifest under the same key is refused. The same package at
another place (the library opened on another machine) records that installation and shares every
other row. One code path does both: nothing is "rebuilt".
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.manifest import (
    ComponentSpec,
    ExportSpec,
    ManifestError,
    PackageManifest,
    file_problems,
    parse_manifest,
)
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    ModelExport,
    RuntimePackage,
    RuntimePackageInstallation,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.package_store import MANIFEST_FILE, InstalledPackage
from backend.app.runtime.repository import RuntimeCatalogRepository
from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, StorageMode

DETECTOR = "FACE_DETECTOR"
EMBEDDER = "FACE_REPRESENTATION"
REGISTERED = "REGISTERED"
INSTALLED = "INSTALLED"
DECLARED = "DECLARED"
FINGERPRINT_SCHEME = "rs1"
_DETECTOR_KEYS = {"preprocessing_contract"}
_EMBEDDER_KEYS = {
    "family",
    "dimension",
    "preprocessing_contract",
    "normalization",
    "normalization_contract_version",
    "compatibility_version",
}


class RegistrationError(Exception):
    """A package that cannot be registered. Nothing of it is left in the caller's transaction
    that the caller does not roll back."""


@dataclass(frozen=True, slots=True)
class RegisteredExport:
    file: str  # the manifest's name for it
    component_key: str
    kind: str
    component_version_id: uuid.UUID
    model_export_id: uuid.UUID
    artifact_id: uuid.UUID
    variant_ids: Mapping[str, uuid.UUID]  # variant key -> RuntimeVariant id
    representation_space_id: uuid.UUID | None  # only for an embedder's export


@dataclass(frozen=True, slots=True)
class RegisteredPackage:
    runtime_package_id: uuid.UUID
    installation_id: uuid.UUID
    exports: tuple[RegisteredExport, ...]


def space_identity(contract: Mapping[str, Any], weights_digest: str) -> dict[str, Any]:
    """The record a representation space is identified by (ML 18.1). No execution provider."""
    return {
        "family": contract["family"],
        "weights_digest": weights_digest,
        "dimension": contract["dimension"],
        "preprocessing_contract": contract["preprocessing_contract"],
        "normalization": contract["normalization"],
        "normalization_contract_version": contract["normalization_contract_version"],
        "model_compatibility_version": contract["compatibility_version"],
    }


def space_key(identity: Mapping[str, Any]) -> str:
    """The fingerprint of an identity: canonical JSON (sorted keys, no spaces), hashed."""
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{FINGERPRINT_SCHEME}:{hashlib.sha256(canonical.encode('ascii')).hexdigest()}"


def _check_contracts(manifest: PackageManifest) -> None:
    for component in manifest.components:
        contract = component.contract
        if component.kind == DETECTOR:
            expected = _DETECTOR_KEYS
        elif component.kind == EMBEDDER:
            expected = _EMBEDDER_KEYS
        else:
            raise RegistrationError(
                f"component {component.key!r} has the kind {component.kind!r}, which is not "
                f"{DETECTOR} or {EMBEDDER}"
            )
        missing = expected - contract.keys()
        if missing:
            raise RegistrationError(
                f"component {component.key!r}: contract lacks {sorted(missing)}"
            )
        for name in expected:
            value = contract[name]
            if name == "dimension":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise RegistrationError(
                        f"component {component.key!r}: dimension must be a positive integer"
                    )
            elif not isinstance(value, str) or not value:
                raise RegistrationError(
                    f"component {component.key!r}: {name} must be a non-empty string"
                )


class _Registrar:
    def __init__(
        self,
        session: Session,
        package: InstalledPackage,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self.session = session
        self.catalog = RuntimeCatalogRepository(session)
        self.package = package
        self.manifest = package.manifest
        self.new_id = new_id
        self.now = clock()

    def run(self, manifest_bytes: bytes) -> RegisteredPackage:
        stored: dict[str, Any] = json.loads(manifest_bytes)
        components = {c.key: c for c in self.manifest.components}
        versions = {key: self._component_version(spec) for key, spec in components.items()}
        row = self.catalog.package_by_key(self.manifest.key)
        if row is None:
            row = self.catalog.add(
                RuntimePackage(
                    id=self.new_id(),
                    key=self.manifest.key,
                    manifest_schema_version=self.manifest.schema_version,
                    manifest_json=stored,
                    state=REGISTERED,
                    created_at=self.now,
                )
            )
        elif row.manifest_json != stored:
            raise RegistrationError(
                f"{self.manifest.key}: a different package is registered under this key"
            )
        installation = self._installation(row, manifest_bytes)
        exports = tuple(
            self._export(spec, components[spec.component], versions[spec.component])
            for spec in self.manifest.exports
        )
        return RegisteredPackage(row.id, installation.id, exports)

    def _installation(
        self, row: RuntimePackage, manifest_bytes: bytes
    ) -> RuntimePackageInstallation:
        """This machine's installation of the package: found by where it is, or recorded. The
        package row is shared by every machine that opens the library; where the bytes are is not
        (the path names the package's own directory, so it identifies the package too).
        The artifact is the manifest file, not the directory: an artifact is file-like and startup
        checks that a referenced one is a regular file."""
        path = str(self.package.path / MANIFEST_FILE)
        found = self.session.scalar(
            select(RuntimePackageInstallation)
            .join(Artifact, Artifact.id == RuntimePackageInstallation.artifact_id)
            .where(Artifact.external_path == path)
        )
        if found is not None:
            return found
        artifact = self._artifact(
            ArtifactKind.RUNTIME_PACKAGE,
            path,
            hashlib.sha256(manifest_bytes).digest(),
            len(manifest_bytes),
            MANIFEST_FILE,
        )
        return self.catalog.add(
            RuntimePackageInstallation(
                id=self.new_id(),
                runtime_package_id=row.id,
                artifact_id=artifact.id,
                state=INSTALLED,
                installed_at=self.now,
            )
        )

    # --- components ------------------------------------------------------------------------

    def _component_version(self, spec: ComponentSpec) -> ComponentVersion:
        component = self.catalog.component_by_key(spec.key)
        if component is None:
            component = self.catalog.add(
                Component(
                    id=self.new_id(), key=spec.key, kind=spec.kind, display_name=spec.key,
                    state="ACTIVE",
                )
            )  # fmt: skip
        elif component.kind != spec.kind:
            raise RegistrationError(f"component {spec.key!r} is registered as a {component.kind}")
        for version in self.catalog.versions_of(component.id):
            if version.semantic_version == spec.version:
                if version.contract_json != dict(spec.contract):
                    raise RegistrationError(
                        f"component {spec.key!r} {spec.version}: its contract is immutable and "
                        "this package says something else"
                    )
                return version
        return self.catalog.add(
            ComponentVersion(
                id=self.new_id(),
                component_id=component.id,
                semantic_version=spec.version,
                contract_schema_version=1,
                contract_json=dict(spec.contract),
                created_at=self.now,
            )
        )

    # --- exports ---------------------------------------------------------------------------

    def _artifact(
        self, kind: ArtifactKind, path: str, sha256: bytes, size: int, name: str
    ) -> Artifact:
        artifact = Artifact(
            id=self.new_id(),
            kind=kind,
            storage_mode=StorageMode.REFERENCED,
            state=ArtifactState.AVAILABLE,
            external_path=path,
            sha256=sha256,
            size_bytes=size,
            original_filename=name,
            created_at=self.now,
            available_at=self.now,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def _model_artifact(self, spec: ExportSpec, path: Path) -> Artifact:
        return self._artifact(
            ArtifactKind.MODEL_EXPORT, str(path), spec.sha256, spec.size_bytes, path.name
        )

    def _export(
        self, spec: ExportSpec, component: ComponentSpec, version: ComponentVersion
    ) -> RegisteredExport:
        path = self.package.path / spec.file
        export = self.session.scalar(
            select(ModelExport).where(
                ModelExport.component_version_id == version.id, ModelExport.sha256 == spec.sha256
            )
        )
        artifact: Artifact | None = None
        if export is None:
            artifact = self._model_artifact(spec, path)
            export = self.catalog.add(
                ModelExport(
                    id=self.new_id(),
                    component_version_id=version.id,
                    format=spec.format,
                    precision=spec.precision,
                    artifact_id=artifact.id,
                    sha256=spec.sha256,
                    input_contract_json=dict(spec.input_contract),
                    created_at=self.now,
                )
            )
        elif (export.format, export.precision, export.input_contract_json) != (
            spec.format,
            spec.precision,
            dict(spec.input_contract),
        ):
            raise RegistrationError(
                f"{spec.file}: these weights are registered with another format, precision or "
                "input contract, which are immutable"
            )
        installed = self.session.scalar(
            select(InstalledModelExport)
            .join(Artifact, Artifact.id == InstalledModelExport.artifact_id)
            .where(Artifact.external_path == str(path))
        )
        if installed is None:  # (this location is new: the weights may be known from another)
            artifact = artifact or self._model_artifact(spec, path)
            installed = self.catalog.add(
                InstalledModelExport(
                    id=self.new_id(),
                    model_export_id=export.id,
                    artifact_id=artifact.id,
                    state=INSTALLED,
                    installed_at=self.now,
                )
            )
        space_id = self._space(component, spec, version) if component.kind == EMBEDDER else None
        variants = {
            variant.variant_key: self._variant(export, variant, space_id)
            for variant in self.manifest.variants
            if variant.export_file == spec.file
        }
        return RegisteredExport(
            spec.file, component.key, component.kind, version.id, export.id,
            installed.artifact_id, variants, space_id,
        )  # fmt: skip

    def _variant(self, export: ModelExport, spec: Any, space_id: uuid.UUID | None) -> uuid.UUID:
        row = self.session.scalar(
            select(RuntimeVariant).where(
                RuntimeVariant.model_export_id == export.id,
                RuntimeVariant.variant_key == spec.variant_key,
                RuntimeVariant.provider == spec.provider,
                RuntimeVariant.device_kind == spec.device_kind,
            )
        )
        if row is None:
            row = self.catalog.add(
                RuntimeVariant(
                    id=self.new_id(),
                    model_export_id=export.id,
                    provider=spec.provider,
                    device_kind=spec.device_kind,
                    variant_key=spec.variant_key,
                    requirements_json=dict(spec.requirements),
                    state=REGISTERED,
                )
            )
        elif row.requirements_json != dict(spec.requirements):
            raise RegistrationError(
                f"variant {spec.variant_key!r}: registered with other requirements"
            )
        if (
            space_id is not None
            and self.session.get(RuntimeVariantRepresentationSpace, (row.id, space_id)) is None
        ):
            self.session.add(
                RuntimeVariantRepresentationSpace(
                    runtime_variant_id=row.id,
                    representation_space_id=space_id,
                    validation_json={"declared_by_package": self.manifest.key},
                    state=DECLARED,
                )
            )
            self.session.flush()
        return row.id

    # --- representation spaces ---------------------------------------------------------------

    def _space(
        self, component: ComponentSpec, spec: ExportSpec, version: ComponentVersion
    ) -> uuid.UUID:
        identity = space_identity(component.contract, spec.sha256.hex())
        key = space_key(identity)
        record = identity | {"fingerprint_scheme": FINGERPRINT_SCHEME}
        space = self.session.scalar(
            select(RepresentationSpace).where(RepresentationSpace.semantic_key == key)
        )
        if space is None:
            space = RepresentationSpace(
                id=self.new_id(),
                semantic_key=key,
                state="ACTIVE",
                dimension=identity["dimension"],
                metric="COSINE",
                normalization=identity["normalization"],
                component_version_id=version.id,
                contract_schema_version=1,
                contract_json=record,
                created_at=self.now,
            )
            self.session.add(space)
            self.session.flush()
        elif space.contract_json != record:
            raise RegistrationError(f"space {key} is registered with another identity record")
        return space.id


def register_package(
    session: Session,
    package: InstalledPackage,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> RegisteredPackage:
    """Record `package` in the catalog, inside the caller's transaction (see the module doc).

    What is recorded is what is on disk now: the package must live in the directory named by its
    key, its manifest file must parse to the manifest given, and every declared file must still
    have its declared size and hash (the weights digest is the identity of a representation space,
    so it is never copied from a claim). The work is done in a savepoint, so a refused
    registration leaves nothing in the caller's transaction even if the caller commits anyway.
    Find-or-create reads before it writes: run it inside `UnitOfWork.write`, which takes the write
    lock first, or a concurrent registration surfaces as an `IntegrityError` (it fails safe).
    """
    manifest = package.manifest
    if package.path.name != manifest.key:
        raise RegistrationError(
            f"{manifest.key}: the package is not in the directory its key names"
        )
    try:
        manifest_bytes = (package.path / MANIFEST_FILE).read_bytes()
        on_disk = parse_manifest(manifest_bytes)
    except (OSError, ManifestError) as error:
        raise RegistrationError(f"{manifest.key}: the manifest cannot be read ({error})") from error
    if on_disk != manifest:
        raise RegistrationError(f"{manifest.key}: the manifest on disk is not the one given")
    problems = file_problems(package.path, manifest)
    if problems:
        raise RegistrationError(f"{manifest.key}: " + "; ".join(problems))
    _check_contracts(manifest)
    with session.begin_nested():
        return _Registrar(session, package, new_id, clock).run(manifest_bytes)
