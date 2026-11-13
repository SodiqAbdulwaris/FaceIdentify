"""The recognition mode the user chooses (API section 5.9; M8 step 5(b), R7).

`GET /runtime/recognition-mode` answers the current mode (`NONE` before a choice) and the two
options with the exact policy each would write. `PUT /runtime/recognition-mode` writes the chosen
one; it needs the version the user was shown, and never replaces a policy file this application did
not write. The policy is read on every request by the real profile, so it applies at once.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.dependencies import Library
from backend.api.errors import ApiError
from backend.api.real import PACKAGE_KEY, policy_path
from backend.app.runtime.recognition_mode import (
    POLICIES,
    ModeNotConfirmedError,
    ModeNotRecognisedError,
    RecognitionMode,
    choose_mode,
    current_mode,
)

router = APIRouter(prefix="/runtime/recognition-mode", tags=["runtime"])

DESCRIPTIONS = {
    RecognitionMode.ASSISTED: (
        "Every face after the first waits for you to confirm it. Nothing is matched or "
        "created without you."
    ),
    RecognitionMode.AUTOMATIC: (
        "A face that matches a known person clearly enough (0.45, with a margin of 0.10) is "
        "placed automatically; anything unclear still waits for you. No person is created "
        "automatically."
    ),
}


class ModeOption(BaseModel):
    mode: RecognitionMode
    description: str
    policy: dict[str, Any]


class ModeState(BaseModel):
    mode: str  # NONE, ASSISTED, AUTOMATIC or CUSTOM (a policy the owner made, left alone)
    options: list[ModeOption]


class ChooseMode(BaseModel):
    mode: RecognitionMode
    shown_version: str


def _state(library: Library) -> ModeState:
    try:
        held: str = current_mode(policy_path(library.roots.local_state_root, PACKAGE_KEY)) or "NONE"
    except ModeNotRecognisedError:
        held = "CUSTOM"
    return ModeState(
        mode=held,
        options=[
            ModeOption(mode=mode, description=DESCRIPTIONS[mode], policy=policy)
            for mode, policy in POLICIES.items()
        ],
    )


@router.get("")
def get_mode(library: Library) -> ModeState:
    return _state(library)


@router.put("")
def put_mode(body: ChooseMode, library: Library) -> ModeState:
    path = policy_path(library.roots.local_state_root, PACKAGE_KEY)
    try:
        choose_mode(path, body.mode, body.shown_version)
    except ModeNotConfirmedError:
        raise ApiError(
            409, "POLICY_NOT_CONFIRMED", "That is not the policy you were shown for that mode."
        ) from None
    except ModeNotRecognisedError:
        raise ApiError(
            409,
            "POLICY_NOT_REPLACEABLE",
            "A policy this application did not write is installed and is left as it is.",
        ) from None
    return _state(library)
