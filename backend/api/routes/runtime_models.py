"""The face models the user installs themselves (API section on the runtime; M8 step 5, R6).

`GET /runtime/models` says what the application needs, the licence it comes under and the size
and SHA-256 each file must have, and whether it is installed. `POST /runtime/models/install`
takes the folder or the zip the user obtained and installs it after checking every file against
that table. The weights are never bundled and never downloaded here. After an install the
processing configuration is prepared again, so the package is usable without a restart.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.library_profile import LibraryProfile
from backend.api.startup import Backend
from backend.app.runtime import model_install
from backend.app.runtime.model_install import ModelSourceError, install_models
from backend.app.runtime.package_store import PackageExistsError, PackageInstallError

router = APIRouter(prefix="/runtime/models", tags=["runtime"])


class ModelFile(BaseModel):
    name: str
    size_bytes: int
    sha256: str


class ModelsState(BaseModel):
    package_key: str
    installed: bool
    licence: str
    source_url: str
    files: list[ModelFile]


class InstallModelsRequest(BaseModel):
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("the path must be absolute")
        return value


def _state(library: Library) -> ModelsState:
    return ModelsState(
        package_key=model_install.PACKAGE_KEY,
        installed=library.packages.get(model_install.PACKAGE_KEY) is not None,
        licence=model_install.LICENCE,
        source_url=model_install.SOURCE_URL,
        files=[
            ModelFile(name=known.name, size_bytes=known.size_bytes, sha256=known.sha256)
            for known in model_install.KNOWN_FILES
        ],
    )


@router.get("")
def get_models(library: Library) -> ModelsState:
    return _state(library)


@router.post("/install", status_code=201)
def install(
    body: InstallModelsRequest,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> ModelsState:
    settings = backend.processing
    development = settings is not None and settings.profile is LibraryProfile.DEVELOPMENT
    try:
        install_models(Path(body.path), library.packages, allow_fixture=development)
    except ModelSourceError as error:
        raise ApiError(400, "MODEL_SOURCE_INVALID", str(error)) from None
    except PackageExistsError:
        raise ApiError(
            409, "MODELS_ALREADY_INSTALLED", "Different face models are already installed."
        ) from None
    except PackageInstallError:
        raise ApiError(
            400, "MODEL_SOURCE_INVALID", "The models could not be installed from that source."
        ) from None
    if settings is not None and settings.prepare is not None:
        backend.capabilities.update(settings.prepare(library) or {})
    return _state(library)
