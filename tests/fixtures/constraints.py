"""Exact-match helpers for asserting which database constraint rejected a write."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def check(name: str) -> str:
    """Regex for exactly this CHECK constraint failing (not one whose name merely starts so)."""
    return re.escape(name) + r"(\n|$)"


def unique(*columns: str) -> str:
    """Regex for exactly this UNIQUE column set failing, in SQLite's message format."""
    return "UNIQUE constraint failed: " + re.escape(", ".join(columns)) + r"(\n|$)"


def rejected(session: Session, make: Callable[[], Any], constraint: str) -> None:
    """Assert that `make()` violates the given constraint.

    The write runs inside a SAVEPOINT, so only the failed write is undone. Rows created earlier
    in the test survive, and later assertions in the same test still see them.
    """
    with pytest.raises(IntegrityError, match=constraint), session.begin_nested():
        make()
