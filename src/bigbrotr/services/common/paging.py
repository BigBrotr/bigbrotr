"""Shared keyset-pagination helpers for service query modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


_PageToken = TypeVar("_PageToken")
_Item = TypeVar("_Item")


async def iter_keyset_pages(
    fetch_page: Callable[
        [_PageToken | None, int],
        Awaitable[tuple[list[_Item], _PageToken | None]],
    ],
    *,
    page_size: int,
    max_items: int | None = None,
) -> AsyncIterator[list[_Item]]:
    """Yield bounded pages produced by a keyset-paginated fetch function."""
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    if max_items is not None and max_items < 0:
        raise ValueError("max_items must be >= 0")

    remaining = max_items
    token: _PageToken | None = None

    while True:
        limit = page_size if remaining is None else min(page_size, remaining)
        if limit == 0:
            return

        page, token = await fetch_page(token, limit)
        if not page:
            return

        yield page

        if remaining is not None:
            remaining -= len(page)
            if remaining <= 0:
                return

        if token is None or len(page) < limit:
            return
