"""The third-party notices generator (M8 step 1): what it flags, how it renders, what it covers."""

import json
from pathlib import Path

from scripts import generate_notices as notices


def component(
    licence: str, texts: dict[str, str] | None = None, name: str = "pkg"
) -> notices.Component:
    return notices.Component("python", name, "1.0", licence, texts or {})


def test_a_component_without_a_licence_identifier_is_a_problem() -> None:
    assert component("").problems == ["no licence identifier"]


def test_copyleft_licences_that_cannot_ship_are_problems_but_the_lgpl_only_needs_review() -> None:
    assert component("GPL-3.0-only").problems
    assert component("AGPL-3.0-or-later").problems
    lgpl = component("LGPL-2.1-or-later")
    assert lgpl.problems == []
    assert lgpl.needs_review


def test_a_gpl_part_is_never_hidden_by_an_lgpl_part_but_an_or_may_choose_around_it() -> None:
    assert component("GPL-2.0-only AND LGPL-2.1-only").problems
    assert component("LGPL-2.1-only AND GPL-3.0-or-later").problems
    assert component("GPL-2.0-only OR MIT").problems == []
    assert component("GPL-2.0-only OR AGPL-3.0-only").problems


def test_a_permissive_component_is_clean_and_file_level_copyleft_needs_review() -> None:
    assert component("MIT").problems == []
    assert not component("MIT").needs_review
    assert component("MPL-2.0 AND MIT").needs_review


def test_notices_list_every_component_and_print_one_text_for_identical_licences() -> None:
    mit = "MIT License\n\nPermission is hereby granted"
    rendered = notices.render(
        [
            component("MIT", {"LICENSE": mit}, "alpha"),
            component("MIT", {"LICENSE.txt": mit}, "beta"),
            component("Apache-2.0", {}, "gamma"),
        ]
    )
    assert rendered.count("Permission is hereby granted") == 1
    assert "Used by: alpha 1.0, beta 1.0" in rendered
    assert "| python | gamma | 1.0 | Apache-2.0 |" in rendered
    assert "- python: gamma 1.0: Apache-2.0" in rendered  # no licence file: declared only


def test_every_frontend_dependency_is_classified_as_bundled_or_not() -> None:
    manifest = json.loads((notices.ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    classified = notices.NPM_BUNDLED | notices.NPM_INLINED_CSS | notices.NPM_NOT_SHIPPED
    assert set(manifest["dependencies"]) <= classified


def test_the_runtime_python_closure_carries_licence_texts() -> None:
    found = {c.name.lower(): c for c in notices.python_components()}
    assert found["fastapi"].licence == "MIT"
    assert found["fastapi"].texts
    assert "pytest" not in found  # development packages are not shipped


def test_the_wheel_that_carries_directml_also_carries_microsofts_terms() -> None:
    found = {c.name.lower(): c for c in notices.python_components()}
    runtime = found.get("onnxruntime-windowsml")
    if runtime is not None:  # the Windows build; other platforms install the plain CPU package
        assert runtime.missing == []
        assert "DirectML-LICENSE.txt" in runtime.texts


def test_the_runtime_bundle_names_cpython_with_its_licence_and_the_libraries_it_links() -> None:
    found = {c.name.split(" (")[0]: c for c in notices.bundled_components()}
    assert found["CPython"].texts
    assert not found["CPython"].problems
    assert {"OpenSSL", "SQLite", "libffi"} <= found.keys()
    assert "FFmpeg" not in found  # only a build that ships it lists it


def test_ffmpeg_is_listed_with_its_licence_text_and_refused_without_one(tmp_path: Path) -> None:
    (tmp_path / "LICENSE.txt").write_text("GNU LESSER GENERAL PUBLIC LICENSE", encoding="utf-8")
    shipped = notices.bundled_components(tmp_path)[-1]
    assert shipped.name.startswith("FFmpeg")
    assert shipped.texts == {"LICENSE.txt": "GNU LESSER GENERAL PUBLIC LICENSE"}
    assert shipped.problems == []
    assert shipped.needs_review  # the LGPL: the owner reviewed it (D2), the build still says so

    (tmp_path / "LICENSE.txt").unlink()
    assert notices.bundled_components(tmp_path)[-1].problems
