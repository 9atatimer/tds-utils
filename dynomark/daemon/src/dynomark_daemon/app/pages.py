"""Pages and cursors (contract/v1 README, Delivery and replay: Pagination).

A cursor is opaque to the extension and valid only for the list and the
request parameters that minted it; presented with others it is stale.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from dynomark_daemon.app.errors import UseCaseError

_SEPARATOR: Final = "~"


class StaleCursor(UseCaseError):
    """The cursor expired or belongs to other parameters (``stale_cursor``)."""


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a list; ``next_cursor`` is ``None`` on the last page."""

    items: tuple[T, ...]
    next_cursor: str | None


def _digest(params: str) -> str:
    return hashlib.sha256(params.encode("utf-8")).hexdigest()[:16]


def mint_cursor(kind: str, params: str, key: str) -> str:
    """A cursor for ``kind`` under ``params`` resuming after ``key`` (an id)."""
    return _SEPARATOR.join((kind, _digest(params), key))


def read_cursor(cursor: str, kind: str, params: str) -> str:
    """The key a cursor resumes after.

    Raises:
        StaleCursor: it was minted for another list or other parameters.
    """
    parts = cursor.split(_SEPARATOR)
    if len(parts) != 3 or parts[:2] != [kind, _digest(params)]:
        raise StaleCursor(f"cursor is not one of this {kind} list")
    return parts[2]


def paginate[T](
    rows: Sequence[T],
    key: Callable[[T], str],
    *,
    kind: str,
    params: str,
    cursor: str | None,
    limit: int,
) -> Page[T]:
    """Up to ``limit`` rows after the cursor's key, in ``rows``' order.

    Raises:
        StaleCursor: the cursor is foreign, or its row has left the list.
    """
    start = 0
    if cursor is not None:
        after = read_cursor(cursor, kind, params)
        keys = [key(row) for row in rows]
        if after not in keys:
            raise StaleCursor(f"the {kind} list changed under the cursor")
        start = keys.index(after) + 1
    items = tuple(rows[start : start + limit])
    more = start + limit < len(rows)
    return Page(
        items=items,
        next_cursor=mint_cursor(kind, params, key(items[-1])) if more else None,
    )


def offset_page[T](
    rows: Sequence[T], *, kind: str, params: str, cursor: str | None, limit: int
) -> Page[T]:
    """Up to ``limit`` rows after the cursor's offset into ``rows``: for a list
    recomputed on each request (a ranking), whose rows have no short key.

    Raises:
        StaleCursor: the cursor is foreign or does not name an offset.
    """
    start = 0
    if cursor is not None:
        key = read_cursor(cursor, kind, params)
        if not key.isdecimal():
            raise StaleCursor(f"{kind} cursor does not name an offset")
        start = int(key)
    items = tuple(rows[start : start + limit])
    end = start + len(items)
    return Page(
        items=items,
        next_cursor=mint_cursor(kind, params, str(end)) if end < len(rows) else None,
    )
