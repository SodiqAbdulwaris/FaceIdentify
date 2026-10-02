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
* a `REFERENCED` artifact for each export's file and for the package directory (the bytes stay
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

Registering the same package again (same key, same manifest) finds what it made and returns the
same ids; a different manifest under the same key is refused.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.manifest import ComponentSpec, ExportSpec, PackageManifest
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

    def run(self) -> RegisteredPackage:
        manifest_bytes = (self.package.path / MANIFEST_FILE).read_bytes()
        stored: dict[str, Any] = json.loads(manifest_bytes)
        existing = self.catalog.package_by_key(self.manifest.key)
        if existing is not None:
            if existing.manifest_json != stored:
                raise RegistrationError(
                    f"{self.manifest.key}: a different package is registered under this key"
                )
            return self._rebuild(existing)
        components = {c.key: c for c in self.manifest.components}
        versions = {key: self._component_version(spec) for key, spec in components.items()}
        package_artifact = self._artifact(
            ArtifactKind.RUNTIME_PACKAGE,
            str(self.package.path),
            hashlib.sha256(manifest_bytes).digest(),
            len(manifest_bytes),
            MANIFEST_FILE,
        )
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
        installation = self.catalog.add(
            RuntimePackageInstallation(
                id=self.new_id(),
                runtime_package_id=row.id,
                artifact_id=package_artifact.id,
                state=INSTALLED,
                installed_at=self.now,
            )
        )
        exports = tuple(
            self._export(spec, components[spec.component], versions[spec.component])
            for spec in self.manifest.exports
        )
        return RegisteredPackage(row.id, installation.id, exports)

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

    def _export(
        self, spec: ExportSpec, component: ComponentSpec, version: ComponentVersion
    ) -> RegisteredExport:
        path = self.package.path / spec.file
        artifact = self._artifact(
            ArtifactKind.MODEL_EXPORT, str(path), spec.sha256, spec.size_bytes, path.name
        )
        export = self.session.scalar(
            select(ModelExport).where(
                ModelExport.component_version_id == version.id, ModelExport.sha256 == spec.sha256
            )
        )
        if export is None:
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
        self.catalog.add(
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
            spec.file, component.key, component.kind, version.id, export.id, artifact.id,
            variants, space_id,
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

    # --- registering again -------------------------------------------------------------------

    def _rebuild(self, package_row: RuntimePackage) -> RegisteredPackage:
        """What a first registration of this package made, found again from the catalog."""
        installation = self.catalog.package_installations(package_row.id)[0]
        components = {c.key: c for c in self.manifest.components}
        exports: list[RegisteredExport] = []
        for spec in self.manifest.exports:
            component = components[spec.component]
            row = self.catalog.component_by_key(component.key)
            assert row is not None  # (registered with the package)
            version = next(
                v
                for v in self.catalog.versions_of(row.id)
                if v.semantic_version == component.version
            )
            export = self.session.scalars(
                select(ModelExport).where(
                    ModelExport.component_version_id == version.id,
                    ModelExport.sha256 == spec.sha256,
                )
            ).one()
            installed = self.session.scalars(
                select(InstalledModelExport)
                .join(Artifact, Artifact.id == InstalledModelExport.artifact_id)
                .where(
                    InstalledModelExport.model_export_id == export.id,
                    Artifact.external_path == str(self.package.path / spec.file),
                )
            ).one()
            space_id = None
            if component.kind == EMBEDDER:
                identity = space_identity(component.contract, spec.sha256.hex())
                space_id = self.session.scalars(
                    select(RepresentationSpace.id).where(
                        RepresentationSpace.semantic_key == space_key(identity)
                    )
                ).one()
            variants = {
                v.variant_key: self._variant(export, v, space_id)
                for v in self.manifest.variants
                if v.export_file == spec.file
            }
            exports.append(
                RegisteredExport(
                    spec.file,
                    component.key,
                    component.kind,
                    version.id,
                    export.id,
                    installed.artifact_id,
                    variants,
                    space_id,
                )  # fmt: skip
            )
        return RegisteredPackage(package_row.id, installation.id, tuple(exports))


def register_package(
    session: Session,
    package: InstalledPackage,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> RegisteredPackage:
    """Record `package` in the catalog, inside the caller's transaction (see the module doc)."""
    _check_contracts(package.manifest)
    return _Registrar(session, package, new_id, clock).run()
