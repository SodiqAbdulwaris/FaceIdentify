"""How automatic recognition is: the user's choice of one of two policies (M8 step 5(b), R7).

The package ships no policy and never overwrites one. Without a policy processing is unavailable
and says so. The first-run flow offers *Assisted* recognition (the abstain-only policy: every face
after the first waits for the user) as the default, and *Automatic* recognition (the owner-approved
operating point, 0.45 with a margin of 0.10, no automatic new identity) only when the user chooses
it after being shown exactly what will be written. A policy file that is neither of these two (a
measured one the owner made) is never replaced by this module.
"""

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any


class RecognitionMode(StrEnum):
    ASSISTED = "ASSISTED"
    AUTOMATIC = "AUTOMATIC"


class ModeNotRecognisedError(Exception):
    """A policy file this application did not write is in the way; it is left as it is."""


class ModeNotConfirmedError(Exception):
    """The version the user was shown is not the version of the mode they chose."""


POLICIES: dict[RecognitionMode, dict[str, Any]] = {
    RecognitionMode.ASSISTED: {
        "schema_version": 1,
        "version": "buffalo-l-abstain-only-v1",
        "min_detection_score": 0.5,
        "new_identity_ceiling": -1.0,
        "match_threshold": 2.0,
        "margin": 2.0,
    },
    RecognitionMode.AUTOMATIC: {
        "schema_version": 1,
        "version": "buffalo-l-verified-match-v1",
        "min_detection_score": 0.5,
        "new_identity_ceiling": -1.0,
        "match_threshold": 0.45,
        "margin": 0.1,
    },
}


def current_mode(path: Path) -> RecognitionMode | None:
    """The mode the file at `path` holds, or `None` when there is no file. A file that is not
    exactly one of the two policies raises `ModeNotRecognisedError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        raise ModeNotRecognisedError("the policy file cannot be read") from None
    try:
        held = json.loads(text)
    except ValueError:
        raise ModeNotRecognisedError(
            "the policy file is not a policy this application wrote"
        ) from None
    for mode, policy in POLICIES.items():
        if held == policy:
            return mode
    raise ModeNotRecognisedError("the policy file is not a policy this application wrote")


def choose_mode(path: Path, mode: RecognitionMode, shown_version: str) -> None:
    """Write the policy of `mode` at `path`. `shown_version` is the version the user was shown for
    that mode; a different one means they were shown something else and nothing is written. A file
    that is neither of the two policies is left alone (`ModeNotRecognisedError`)."""
    policy = POLICIES[mode]
    if shown_version != policy["version"]:
        raise ModeNotConfirmedError("the policy shown is not the policy of that mode")
    if current_mode(path) is mode:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial")
    partial.write_text(json.dumps(policy), encoding="utf-8")
    os.replace(partial, path)  # the old policy or the new one, never half of either
