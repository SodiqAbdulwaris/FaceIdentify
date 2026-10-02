"""The ML worker's configuration, built from the catalog and this machine's installed packages
(issue 80: a missing required runtime package is reported, never substituted).

A processing run names the detector component version it wants and the representation space it
produces. This module turns that into the variants the worker may run, in the order the backend
wants to try them (the backend, not the worker, decides CUDA-to-CPU fallback, so the caller names
the allowed execution providers in order of preference), and into the worker's JSON configuration
(`backend.ml.worker.perception_handlers.parse_config`).

Every variant offered is one that can run *here and now*:

* the library records where each installation of an export is (`InstalledModelExport` and its
  referenced artifact); only a record inside this machine's runtime-package directory counts, so a
  library opened on another machine, or a record that points anywhere else, never becomes a model
  path the worker would open;
* that path must be a file the installed package's manifest declares, with the manifest's digest
  for the export the catalog says it is, and the package's files must still match their manifest
  (`RuntimePackageStore.verify`), so a package that was damaged or replaced since it was registered
  is not offered;
* the variant's provider must be one the caller allows.

If a required component has no such variant the answer is `RuntimeUnavailableError`, listing each
reason, and nothing else is substituted: not another component version, not another space, not a
model that merely loads. The detector and the embedder are required separately.
"""

import json
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.registration import (
    DECLARED,
    DETECTOR,
    EMBEDDER,
    INSTALLED,
    REGISTERED,
    VALIDATED,
)
from backend.app.sources.models import Artifact, ArtifactState

# The compatibility states under which a variant may produce a space's vectors. `DECLARED` is the
# manifest's claim (registration); `VALIDATED` is reserved for the later equivalence validation.
USABLE_COMPATIBILITY = (DECLARED, VALIDATED)
# The states a runtime variant itself may be in to be planned (a retired or failed one is not).
USABLE_VARIANT_STATES = (REGISTERED, VALIDATED)


class RuntimeUnavailableError(Exception):
    """A required component cannot run on this machine. `reasons` says why, one per candidate."""

    def __init__(self, what: str, reasons: Sequence[str]) -> None:
        self.what = what
        self.reasons = tuple(reasons)
        super().__init__(f"{what} is not available here: " + "; ".join(self.reasons))


@dataclass(frozen=True, slots=True)
class PlannedVariant:
    component_version_id: uuid.UUID
    runtime_variant_id: uuid.UUID
    kind: str  # FACE_DETECTOR or FACE_REPRESENTATION
    contract: str  # the pre/postprocessing contract the component version needs
    provider: str
    device: str
    package_key: str
    model_path: Path  # inside this machine's package directory, resolved
    sha256: bytes


@dataclass(frozen=True, slots=True)
class PerceptionPlan:
    representation_space_id: uuid.UUID
    dimension: int
    detector: tuple[PlannedVariant, ...]  # in the order to try
    embedder: tuple[PlannedVariant, ...]

    def worker_config(self) -> str:
        """The configuration text the worker is started with."""
        entries: list[dict[str, Any]] = []
        for variant in (*self.detector, *self.embedder):
            entry: dict[str, Any] = {
                "component_version_id": str(variant.component_version_id),
                "contract": variant.contract,
                "kind": variant.kind,
                "runtime_variant_id": str(variant.runtime_variant_id),
                "model_path": str(variant.model_path),
                "sha256": variant.sha256.hex(),
                "provider": variant.provider,
                "device": variant.device,
            }
            if variant.kind == EMBEDDER:
                entry["dimension"] = self.dimension
            entries.append(entry)
        return json.dumps({"variants": entries})


class _Machine:
    """What this machine has installed, checked at most once per package per plan."""

    def __init__(self, store: RuntimePackageStore) -> None:
        self._store = store
        self._root = store.root.resolve()
        self._problems: dict[str, list[str]] = {}

    def locate(self, artifact: Artifact, export: ModelExport) -> tuple[str, Path] | str:
        """(package key, verified model path) for an installation of `export`, or why not."""
        if artifact.state != ArtifactState.AVAILABLE:
            return f"the installation is recorded as {artifact.state}"
        assert artifact.external_path is not None  # (a REFERENCED artifact always has one)
        path = Path(artifact.external_path)
        try:
            relative = path.resolve().relative_to(self._root)
        except (ValueError, OSError):
            return f"{path} is not in this machine's runtime-package directory"
        if len(relative.parts) < 2:
            return f"{path} is not a file of an installed package"
        key, file = relative.parts[0], "/".join(relative.parts[1:])
        package = self._store.get(key)
        if package is None:
            return f"the package {key!r} is not installed on this machine"
        declared = next((e for e in package.manifest.exports if e.file == file), None)
        if declared is None or declared.sha256 != export.sha256:
            return f"{file} in package {key!r} is not the recorded export"
        if key not in self._problems:
            self._problems[key] = self._store.verify(key)
        if self._problems[key]:
            return f"package {key!r} is damaged: " + "; ".join(self._problems[key])
        return key, self._root / relative  # (the confined path itself, never a link to it)


def _variants_of(
    session: Session,
    machine: _Machine,
    exports: Sequence[ModelExport],
    kind: str,
    providers: Sequence[str],
    allowed: Collection[uuid.UUID] | None,
    reasons: list[str],
) -> list[PlannedVariant]:
    """The variants of `exports` that can run here, preferred provider first. `allowed` limits
    them to those ids (the variants validated for a space); `reasons` collects why not."""
    found: list[PlannedVariant] = []
    for export in exports:
        installs = session.scalars(
            select(InstalledModelExport).where(
                InstalledModelExport.model_export_id == export.id,
                InstalledModelExport.state == INSTALLED,
            )
        ).all()
        located: tuple[str, Path] | None = None
        for installation in installs:
            artifact = session.get(Artifact, installation.artifact_id)
            assert artifact is not None  # (a foreign key)
            where = machine.locate(artifact, export)
            if isinstance(where, str):
                reasons.append(where)
            else:
                located = where
                break
        if located is None:
            if not installs:
                reasons.append(f"no installation of export {export.id} is recorded")
            continue
        version = session.get(ComponentVersion, export.component_version_id)
        assert version is not None  # (a foreign key)
        variants = session.scalars(
            select(RuntimeVariant).where(RuntimeVariant.model_export_id == export.id)
        ).all()
        for variant in variants:
            if allowed is not None and variant.id not in allowed:
                continue
            if variant.state not in USABLE_VARIANT_STATES:
                reasons.append(f"variant {variant.variant_key!r} is {variant.state}")
                continue
            if variant.provider not in providers:
                reasons.append(f"variant {variant.variant_key!r} needs {variant.provider}")
                continue
            found.append(
                PlannedVariant(
                    component_version_id=version.id,
                    runtime_variant_id=variant.id,
                    kind=kind,
                    contract=str(version.contract_json["preprocessing_contract"]),
                    provider=variant.provider,
                    device=variant.device_kind,
                    package_key=located[0],
                    model_path=located[1],
                    sha256=export.sha256,
                )
            )
    return sorted(found, key=lambda v: (providers.index(v.provider), str(v.runtime_variant_id)))


def plan_perception(
    session: Session,
    store: RuntimePackageStore,
    *,
    detector_component_version_id: uuid.UUID,
    representation_space_id: uuid.UUID,
    providers: Sequence[str],
) -> PerceptionPlan:
    """The variants that can detect faces and produce `representation_space_id`'s vectors on
    this machine, preferred providers first. `RuntimeUnavailableError` if either is impossible."""
    machine = _Machine(store)
    space = session.get(RepresentationSpace, representation_space_id)
    if space is None:
        raise RuntimeUnavailableError("the representation space", ["it is not in the library"])
    detector_version = session.get(ComponentVersion, detector_component_version_id)
    if detector_version is None:
        raise RuntimeUnavailableError("the detector", ["its component version is not recorded"])
    component = session.get(Component, detector_version.component_id)
    assert component is not None  # (a foreign key)
    if component.kind != DETECTOR:
        raise RuntimeUnavailableError("the detector", [f"that component is a {component.kind}"])

    detector_reasons: list[str] = []
    detector = _variants_of(
        session,
        machine,
        session.scalars(
            select(ModelExport).where(ModelExport.component_version_id == detector_version.id)
        ).all(),
        DETECTOR,
        providers,
        None,
        detector_reasons,
    )
    if not detector:
        raise RuntimeUnavailableError("the detector", detector_reasons or ["no export is recorded"])

    # The embedder is whatever the library validated for the space: its variants say which
    # exports (the space's weights) and, through them, which component versions.
    compatible = session.scalars(
        select(RuntimeVariant)
        .join(
            RuntimeVariantRepresentationSpace,
            RuntimeVariantRepresentationSpace.runtime_variant_id == RuntimeVariant.id,
        )
        .where(
            RuntimeVariantRepresentationSpace.representation_space_id == space.id,
            RuntimeVariantRepresentationSpace.state.in_(USABLE_COMPATIBILITY),
        )
    ).all()
    embedder_reasons: list[str] = []
    embedder = _variants_of(
        session,
        machine,
        session.scalars(
            select(ModelExport).where(ModelExport.id.in_({v.model_export_id for v in compatible}))
        ).all(),
        EMBEDDER,
        providers,
        {v.id for v in compatible},
        embedder_reasons,
    )
    if not embedder:
        raise RuntimeUnavailableError(
            "the representation model",
            embedder_reasons or ["no variant is validated for the space"],
        )
    return PerceptionPlan(space.id, space.dimension, tuple(detector), tuple(embedder))
