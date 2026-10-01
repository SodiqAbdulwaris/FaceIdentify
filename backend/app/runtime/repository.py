"""RuntimeCatalogRepository: the runtime, component and package metadata
(PERSISTENCE_IMPLEMENTATION.md §18, §26: "cohesive catalog reads/writes").

Like the other repositories it joins the caller's transaction and never commits, and every change
is one statement decided by the database.

The hierarchy is `Component -> ComponentVersion -> ModelExport -> RuntimeVariant`, alongside
`RecognitionCalibrationProfile` and `RuntimePackage`. Those rows are *metadata*: a version, an
export and a calibration profile are immutable (a calibration change creates a new profile), and
"metadata rows are retained after uninstall; only installation records change" (§18). So this
repository can `add` a new catalog row (an already-persistent one is refused: flushing a modified
one would be an update) but has no update for one, and the only changes to an existing row are the
installation records' states (`transition_export_installation`,
`transition_package_installation`).

Not covered yet, by design: the `state` of a component, a runtime variant, a variant's compatibility
mapping and a package is mutable by nature, but no spec says who changes it or between which values
(open question 11), so there is no write path for those until the first use case that needs one.
Their reads (`variants_for_space(states=...)`) work on whatever state the rows were added with.

The value sets of `state`, `kind`, `format`, `provider` and the like are still undecided (CONTEXT
open question 11), so every state is the caller's string and a transition only needs the caller to
name the state it expects.
"""

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.base import instance_state

from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    ModelExport,
    RecognitionCalibrationProfile,
    RuntimePackage,
    RuntimePackageInstallation,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)

CatalogRow = (
    Component
    | ComponentVersion
    | ModelExport
    | InstalledModelExport
    | RuntimeVariant
    | RuntimeVariantRepresentationSpace
    | RecognitionCalibrationProfile
    | RuntimePackage
    | RuntimePackageInstallation
)


def _states(states: Collection[str]) -> list[str]:
    """A bare string is a `Collection[str]` too, and would silently become a list of letters."""
    if isinstance(states, str):
        raise TypeError("states must be a collection of state names, not a single string")
    return list(states)


class RuntimeCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add[T: CatalogRow](self, row: T) -> T:
        """Stage a new catalog row and flush, so its constraints (a unique key, an unknown parent,
        a wrong digest length) are checked now. A row that is already persistent is a
        `ValueError`: catalog rows are immutable, and flushing a changed one would update it."""
        if not instance_state(row).transient:
            raise ValueError("a catalog row is added once: it is immutable afterwards")
        self._session.add(row)
        self._session.flush()
        return row

    # --- reads ----------------------------------------------------------------------------

    def component_by_key(self, key: str) -> Component | None:
        return self._session.scalar(
            select(Component).where(Component.key == key).execution_options(populate_existing=True)
        )

    def versions_of(self, component_id: uuid.UUID) -> list[ComponentVersion]:
        """The component's versions, oldest first."""
        return list(
            self._session.scalars(
                select(ComponentVersion)
                .where(ComponentVersion.component_id == component_id)
                .order_by(ComponentVersion.created_at, ComponentVersion.id)
                .execution_options(populate_existing=True)
            )
        )

    def exports_of(self, component_version_id: uuid.UUID) -> list[ModelExport]:
        """The version's model exports, oldest first."""
        return list(
            self._session.scalars(
                select(ModelExport)
                .where(ModelExport.component_version_id == component_version_id)
                .order_by(ModelExport.created_at, ModelExport.id)
                .execution_options(populate_existing=True)
            )
        )

    def variants_for_space(
        self, representation_space_id: uuid.UUID, *, states: Collection[str]
    ) -> list[RuntimeVariant]:
        """The runtime variants validated for a representation space whose compatibility mapping
        is in one of `states`, in a stable order (variant key, then id)."""
        return list(
            self._session.scalars(
                select(RuntimeVariant)
                .join(
                    RuntimeVariantRepresentationSpace,
                    RuntimeVariantRepresentationSpace.runtime_variant_id == RuntimeVariant.id,
                )
                .where(
                    RuntimeVariantRepresentationSpace.representation_space_id
                    == representation_space_id,
                    RuntimeVariantRepresentationSpace.state.in_(_states(states)),
                )
                .order_by(RuntimeVariant.variant_key, RuntimeVariant.id)
                .execution_options(populate_existing=True)
            )
        )

    def calibration_profiles(
        self, representation_space_id: uuid.UUID
    ) -> list[RecognitionCalibrationProfile]:
        """The space's calibration profiles, newest first (a change adds a profile)."""
        return list(
            self._session.scalars(
                select(RecognitionCalibrationProfile)
                .where(
                    RecognitionCalibrationProfile.representation_space_id == representation_space_id
                )
                .order_by(
                    RecognitionCalibrationProfile.created_at.desc(),
                    RecognitionCalibrationProfile.id.desc(),
                )
                .execution_options(populate_existing=True)
            )
        )

    def package_by_key(self, key: str) -> RuntimePackage | None:
        return self._session.scalar(
            select(RuntimePackage)
            .where(RuntimePackage.key == key)
            .execution_options(populate_existing=True)
        )

    def export_installations(self, model_export_id: uuid.UUID) -> list[InstalledModelExport]:
        return list(
            self._session.scalars(
                select(InstalledModelExport)
                .where(InstalledModelExport.model_export_id == model_export_id)
                .order_by(InstalledModelExport.id)
                .execution_options(populate_existing=True)
            )
        )

    def package_installations(
        self, runtime_package_id: uuid.UUID
    ) -> list[RuntimePackageInstallation]:
        return list(
            self._session.scalars(
                select(RuntimePackageInstallation)
                .where(RuntimePackageInstallation.runtime_package_id == runtime_package_id)
                .order_by(RuntimePackageInstallation.id)
                .execution_options(populate_existing=True)
            )
        )

    # --- installation records (the only rows that change) ---------------------------------

    def transition_export_installation(
        self,
        installation_id: uuid.UUID,
        *,
        from_states: Collection[str],
        to_state: str,
        installed_at: datetime | None = None,
        verified_at: datetime | None = None,
        failure_detail: str | None = None,
    ) -> bool:
        """Move a model export's installation record to `to_state` only if it is in one of
        `from_states` now: one guarded `UPDATE`. **Pass every value that should survive:** the times
        and detail are written as given, so `None` (the default) clears them, which is how a failure
        records its detail and a success clears it, and also how an omitted `installed_at` is lost.
        False if the record was not in an expected state."""
        return self._transition(
            InstalledModelExport, installation_id, from_states, to_state,
            installed_at, verified_at, failure_detail,
        )  # fmt: skip

    def transition_package_installation(
        self,
        installation_id: uuid.UUID,
        *,
        from_states: Collection[str],
        to_state: str,
        installed_at: datetime | None = None,
        verified_at: datetime | None = None,
        failure_detail: str | None = None,
    ) -> bool:
        """As `transition_export_installation`, for a runtime package's installation record."""
        return self._transition(
            RuntimePackageInstallation, installation_id, from_states, to_state,
            installed_at, verified_at, failure_detail,
        )  # fmt: skip

    def _transition(
        self,
        model: type[Any],
        installation_id: uuid.UUID,
        from_states: Collection[str],
        to_state: str,
        installed_at: datetime | None,
        verified_at: datetime | None,
        failure_detail: str | None,
    ) -> bool:
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(model)
                .where(model.id == installation_id, model.state.in_(_states(from_states)))
                .values(
                    state=to_state,
                    installed_at=installed_at,
                    verified_at=verified_at,
                    failure_detail=failure_detail,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        return bool(result.rowcount)
