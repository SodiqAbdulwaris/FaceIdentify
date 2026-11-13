"""The recognition mode the user chooses, in the module and through the API (M8 step 5(b), R7)."""

import json
from pathlib import Path

import pytest

from backend.app.runtime.recognition_mode import (
    POLICIES,
    ModeNotConfirmedError,
    ModeNotRecognisedError,
    RecognitionMode,
    choose_mode,
    current_mode,
)
from tests.fixtures.api import Api, error

MODE = "/api/v1/runtime/recognition-mode"
ASSISTED, AUTOMATIC = RecognitionMode.ASSISTED, RecognitionMode.AUTOMATIC


def version(mode: RecognitionMode) -> str:
    return str(POLICIES[mode]["version"])


def test_without_a_file_there_is_no_mode_and_a_choice_writes_exactly_that_policy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policies" / "insightface-buffalo-l.json"
    assert current_mode(path) is None

    choose_mode(path, ASSISTED, version(ASSISTED))

    assert json.loads(path.read_text(encoding="utf-8")) == POLICIES[ASSISTED]
    assert current_mode(path) is ASSISTED
    assert not list(path.parent.glob("*.partial"))


def test_the_user_may_move_between_the_two_modes_and_choosing_the_same_one_changes_nothing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.json"
    choose_mode(path, ASSISTED, version(ASSISTED))
    choose_mode(path, AUTOMATIC, version(AUTOMATIC))
    assert current_mode(path) is AUTOMATIC

    before = path.stat().st_mtime_ns
    choose_mode(path, AUTOMATIC, version(AUTOMATIC))

    assert path.stat().st_mtime_ns == before


def test_a_version_other_than_the_one_shown_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"

    with pytest.raises(ModeNotConfirmedError):
        choose_mode(path, AUTOMATIC, version(ASSISTED))

    assert not path.exists()


@pytest.mark.parametrize(
    "held",
    [
        "not json",
        json.dumps({**POLICIES[AUTOMATIC], "match_threshold": 0.4}),  # a measured policy
        json.dumps([1, 2]),
    ],
)
def test_a_policy_this_application_did_not_write_is_never_replaced(
    tmp_path: Path, held: str
) -> None:
    path = tmp_path / "policy.json"
    path.write_text(held, encoding="utf-8")

    with pytest.raises(ModeNotRecognisedError):
        current_mode(path)
    with pytest.raises(ModeNotRecognisedError):
        choose_mode(path, ASSISTED, version(ASSISTED))

    assert path.read_text(encoding="utf-8") == held


def test_a_policy_file_that_cannot_be_read_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.mkdir()  # (a folder where the file should be)

    with pytest.raises(ModeNotRecognisedError, match="cannot be read"):
        current_mode(path)


async def test_the_options_show_exactly_what_each_choice_would_write(api: Api) -> None:
    state = (await api.client.get(MODE)).json()

    assert state["mode"] == "NONE"
    shown = {option["mode"]: option for option in state["options"]}
    assert shown["ASSISTED"]["policy"] == POLICIES[ASSISTED]
    assert shown["AUTOMATIC"]["policy"]["match_threshold"] == 0.45
    assert "automatically" in shown["AUTOMATIC"]["description"]


async def test_a_choice_is_written_where_the_real_profile_reads_it(api: Api) -> None:
    response = await api.client.put(
        MODE, json={"mode": "ASSISTED", "shown_version": version(ASSISTED)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "ASSISTED"
    written = api.backend.library.roots.local_state_root / "policies" / "insightface-buffalo-l.json"  # type: ignore[union-attr]
    assert json.loads(written.read_text(encoding="utf-8")) == POLICIES[ASSISTED]
    assert (await api.client.get(MODE)).json()["mode"] == "ASSISTED"


async def test_a_version_that_was_not_shown_is_a_conflict(api: Api) -> None:
    response = await api.client.put(MODE, json={"mode": "AUTOMATIC", "shown_version": "other"})

    error(response, 409, "POLICY_NOT_CONFIRMED")
    assert (await api.client.get(MODE)).json()["mode"] == "NONE"


async def test_the_owners_own_policy_is_reported_as_custom_and_never_replaced(api: Api) -> None:
    folder = api.backend.library.roots.local_state_root / "policies"  # type: ignore[union-attr]
    folder.mkdir(parents=True)
    owners = folder / "insightface-buffalo-l.json"
    owners.write_text(json.dumps({**POLICIES[AUTOMATIC], "margin": 0.2}), encoding="utf-8")

    assert (await api.client.get(MODE)).json()["mode"] == "CUSTOM"
    response = await api.client.put(
        MODE, json={"mode": "ASSISTED", "shown_version": version(ASSISTED)}
    )

    error(response, 409, "POLICY_NOT_REPLACEABLE")
    assert json.loads(owners.read_text(encoding="utf-8"))["margin"] == 0.2
