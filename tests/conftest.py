import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

pytest_plugins = [
    "tests.fixtures.deterministic",
    "tests.fixtures.persistence",
    "tests.factories.models",
]

# Deterministic in CI so a failure reproduces locally; randomised exploration otherwise.
settings.register_profile("ci", derandomize=True, deadline=None, print_blob=True)
settings.register_profile("dev", deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

# Every variable Windows/Python uses to locate per-user data. Pointing them at a sandbox means
# code that resolves %LOCALAPPDATA%/<App>, %APPDATA% or Path.home() can never reach real data.
USER_DATA_ENV_VARS = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME")

# tests/<directory>/ -> marker applied to every test collected from it.
DIRECTORY_MARKERS = {
    "unit": "unit",
    "contracts": "contract",  # directory name per IMPLEMENTATION_ARCHITECTURE.md §24
    "property": "property",
    "integration": "integration",
    "recovery": "recovery",
    "security": "security",
    "concurrency": "concurrency",
    "e2e": "e2e",
}


@pytest.fixture(scope="session", autouse=True)
def sandbox_user_data(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Session-scoped (not per-test) so Hypothesis' function-scoped-fixture check stays quiet."""
    home = tmp_path_factory.mktemp("user-home")
    with pytest.MonkeyPatch.context() as mp:
        for name in USER_DATA_ENV_VARS:
            mp.setenv(name, str(home))
        yield home


@pytest.hookimpl(tryfirst=True)  # must mark items before `-m` deselection runs
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    tests_root = Path(__file__).parent
    for item in items:
        relative = Path(item.path).relative_to(tests_root)
        marker = DIRECTORY_MARKERS.get(relative.parts[0])
        if marker:
            item.add_marker(marker)
