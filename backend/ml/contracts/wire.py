"""Strict readers for wire dicts: exact keys, exact types (a bool is not an int)."""

import math
from collections.abc import Mapping
from typing import Any

from backend.ml.contracts.protocol import MLErrorCode, invalid


def as_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise invalid(f"{what} must be an object")
    return value


def exact_keys(
    value: Mapping[str, Any], what: str, required: set[str], optional: frozenset[str] = frozenset()
) -> None:
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise invalid(f"{what}: missing {sorted(missing)}, unexpected {sorted(extra)}")


def string(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise invalid(f"{what} must be a non-empty string")
    return value


def integer(value: Any, what: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(f"{what} must be an integer")
    if minimum is not None and value < minimum:
        raise invalid(f"{what} must be >= {minimum}")
    return value


def number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise invalid(f"{what} must be a finite number")
    return float(value)


def boolean(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise invalid(f"{what} must be a boolean")
    return value


def sequence(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list | tuple):
        raise invalid(f"{what} must be a list")
    return list(value)


def optional_string(value: Any, what: str) -> str | None:
    return None if value is None else string(value, what)


def error_code(value: Any, what: str) -> MLErrorCode:
    try:
        return MLErrorCode(string(value, what))
    except ValueError:
        raise invalid(f"{what}: unknown error code {value!r}") from None
