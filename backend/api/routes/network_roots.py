"""Approved network locations for face search by path (API section 5.10; issue #174, PR A).

The user lists, approves and revokes the shares a path search may read. Approving a location only
records its name: the host is not contacted, so approving an unreachable or unknown name costs
nothing and never makes this computer authenticate anywhere.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.startup import Backend
from backend.app.runtime.network_roots import (
    NetworkRoot,
    NetworkRootInvalidError,
    NetworkRootNotFoundError,
    NetworkRoots,
    NetworkRootsUnreadableError,
)

router = APIRouter(prefix="/settings/network-roots", tags=["settings"])


class NetworkRootView(BaseModel):
    id: str
    path: str
    approved_at: str


class NetworkRootList(BaseModel):
    roots: list[NetworkRootView]


class ApproveNetworkRoot(BaseModel):
    path: str = Field(max_length=1024)


def network_roots(library: Library) -> NetworkRoots:
    return NetworkRoots(library.roots.local_state_root)


def _view(root: NetworkRoot) -> NetworkRootView:
    return NetworkRootView(id=root.id, path=root.path, approved_at=root.approved_at)


def unreadable() -> ApiError:
    return ApiError(
        503, "NETWORK_ROOTS_UNREADABLE",
        "The list of approved locations cannot be read, so none is approved. Nothing was changed.",
        retryable=True,
    )  # fmt: skip


@router.get("")
def list_roots(library: Library) -> NetworkRootList:
    try:
        return NetworkRootList(roots=[_view(root) for root in network_roots(library).approved()])
    except NetworkRootsUnreadableError:
        raise unreadable() from None


@router.post("", status_code=201)
def approve_root(
    body: ApproveNetworkRoot,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> NetworkRootView:
    try:
        return _view(network_roots(library).add(body.path, now=backend.settings.clock()))
    except NetworkRootInvalidError:
        raise ApiError(
            400, "NETWORK_ROOT_INVALID",
            "Give a share such as \\\\server\\share, or a folder on one. "
            "Device paths and web addresses cannot be approved.",
        ) from None  # fmt: skip
    except NetworkRootsUnreadableError:
        raise unreadable() from None


@router.delete("/{root_id}", status_code=204)
def revoke_root(root_id: str, library: Library) -> Response:
    try:
        network_roots(library).revoke(root_id)
    except NetworkRootNotFoundError:
        raise ApiError(404, "NETWORK_ROOT_NOT_FOUND", "That location is not approved.") from None
    except NetworkRootsUnreadableError:
        raise unreadable() from None
    return Response(status_code=204)
