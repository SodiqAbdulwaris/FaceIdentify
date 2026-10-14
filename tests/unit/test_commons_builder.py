"""The licence and category rules of the Commons dataset builder (no network)."""

from typing import Any

import pytest

from evaluation import build_commons_dataset as builder


def meta(name: str) -> dict[str, Any]:
    return {"LicenseShortName": {"value": name}}


@pytest.mark.parametrize(
    "name",
    [
        "CC BY 2.0",
        "CC BY-SA 4.0",
        "CC0",
        "cc-by-sa-3.0",
        "Public domain",
        "PD-USGov-NASA",
        "CC BY 3.0",
    ],
)
def test_free_licences_are_accepted(name: str) -> None:
    assert builder.free_licence(meta(name)) is True


@pytest.mark.parametrize(
    "name", ["CC BY-NC 2.0", "CC BY-NC-SA 3.0", "CC BY-ND 2.0", "Copyrighted free use", "", "GFDL"]
)
def test_non_commercial_no_derivatives_and_unknown_licences_are_refused(name: str) -> None:
    assert builder.free_licence(meta(name)) is False


def test_the_default_acceptance_is_still_public_domain_only() -> None:
    assert builder.public_domain(meta("Public domain")) is True
    assert builder.public_domain(meta("CC BY 2.0")) is False


def test_only_the_persons_own_year_categories_are_followed() -> None:
    person = "Jennifer Lawrence"
    follow = builder.follows
    assert follow(person, "Category:Jennifer Lawrence by year")
    assert follow(person, "Category:Jennifer Lawrence in 2013")
    assert follow(person, "Category:Photographs of Jennifer Lawrence in 2019")
    assert not follow(person, "Category:Katniss Everdeen")
    assert not follow(person, "Category:Signatures of Jennifer Lawrence")
    assert not follow(person, "Category:Jennifer Lopez in 2013")  # another person
    assert not follow(person, "Category:Jennifer Lawrence logos")


def test_year_categories_are_crawled_once_bounded_and_files_are_not_repeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = {
        "Category:Ann": [("subcat", "Category:Ann by year"), ("file", "File:a0.jpg")],
        "Category:Ann by year": [
            ("subcat", "Category:Ann in 2020"),
            ("subcat", "Category:Ann in 2021"),
            ("subcat", "Category:Ann logos"),  # not followed
        ],
        "Category:Ann in 2020": [("file", "File:a1.jpg"), ("file", "File:a0.jpg")],
        "Category:Ann in 2021": [("file", "File:a2.jpg"), ("subcat", "Category:Ann by year")],
    }
    asked: list[str] = []

    def fake_api(**params: str) -> dict[str, Any]:
        asked.append(params["cmtitle"])
        wanted = params["cmtype"].split("|")  # (the real API filters by type, so does this)
        members = [{"title": t} for kind, t in tree.get(params["cmtitle"], []) if kind in wanted]
        return {"query": {"categorymembers": members}}

    monkeypatch.setattr(builder, "api", fake_api)
    files = builder.category_files("Ann", follow_years=True)
    assert sorted(f["title"] for f in files) == ["File:a0.jpg", "File:a1.jpg", "File:a2.jpg"]
    assert len(asked) == len(set(asked))  # a category is read once (the cycle is not followed)
    assert "Category:Ann logos" not in asked

    asked.clear()
    direct = builder.category_files("Ann", follow_years=False)
    assert [f["title"] for f in direct] == ["File:a0.jpg"]
    assert asked == ["Category:Ann"]
