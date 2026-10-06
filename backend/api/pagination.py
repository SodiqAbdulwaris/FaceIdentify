"""Cursor (keyset) pagination (API and Contracts sections 26 to 28).

A growing collection returns `{"items": [...], "page": {"next_cursor", "has_more"}}`, forward only.
The cursor is opaque to the client: a versioned, URL-safe encoding of the ordering key of the last
item plus a *context* string naming the query it belongs to (the resource, its filters, its sort),
so a cursor from one query is refused by another (`400 INVALID_CURSOR`). A route fetches
`limit + 1` rows and `paginate` trims the extra one: its presence is `has_more`. Every ordering a
route uses must end in a unique tie-breaker so the keyset is total.
"""

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final

from fastapi import Depends, Query
from pydantic import BaseModel

from backend.api.errors import ApiError

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
CURSOR_VERSION: Final = 1
_MAX_CURSOR_LENGTH: Final = 512


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool


class Page[T](BaseModel):
    items: list[T]
    page: PageInfo


@dataclass(frozen=True)
class PageParams:
    limit: int
    cursor: str | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=_MAX_CURSOR_LENGTH)] = None,
) -> PageParams:
    return PageParams(limit, cursor)


PageQuery = Annotated[PageParams, Depends(page_params)]


def encode_cursor(context: str, key: Sequence[str | int | float | None]) -> str:
    """An opaque cursor for the position after the item whose ordering key is `key`."""
    payload = json.dumps(
        {"v": CURSOR_VERSION, "c": context, "k": list(key)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def invalid_cursor() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "The cursor is not valid for this request.")


def decode_cursor(cursor: str, context: str) -> list[Any]:
    """The ordering key a cursor holds, or `INVALID_CURSOR` if it is malformed, from another
    version, or was made for a different query."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4))
        data = json.loads(raw)
    except (UnicodeError, binascii.Error, ValueError):
        raise invalid_cursor() from None
    if (
        not isinstance(data, dict)
        or data.get("v") != CURSOR_VERSION
        or data.get("c") != context
        or not isinstance(data.get("k"), list)
        or not all(
            value is None or isinstance(value, str | int | float) for value in data["k"]
        )  # (a key is scalars only: no nested structure from a forged cursor)
    ):
        raise invalid_cursor()
    return list(data["k"])


def paginate[T, R](
    rows: Sequence[R],
    limit: int,
    *,
    context: str,
    key: Callable[[R], Sequence[str | int | float | None]],
    item: Callable[[R], T],
) -> Page[T]:
    """Turn `limit + 1` fetched rows into a page: trim the probe row, and make the next cursor from
    the last row kept."""
    if limit < 1:
        raise ValueError("a page holds at least one item")
    has_more = len(rows) > limit
    kept = list(rows[:limit])
    next_cursor = encode_cursor(context, key(kept[-1])) if has_more else None
    return Page(
        items=[item(row) for row in kept], page=PageInfo(next_cursor=next_cursor, has_more=has_more)
    )
