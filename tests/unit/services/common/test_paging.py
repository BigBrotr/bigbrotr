"""Unit tests for shared keyset-pagination helpers."""

from __future__ import annotations

from typing import cast

import pytest

from bigbrotr.services.common.paging import iter_keyset_pages


class TestIterKeysetPages:
    async def test_yields_pages_until_exhausted(self) -> None:
        pages = {
            None: ([1, 2], 2),
            2: ([3], 3),
            3: ([], None),
        }

        async def fetch_page(token: int | None, limit: int) -> tuple[list[int], int | None]:
            page, next_token = pages[token]
            return cast("list[int]", page[:limit]), next_token

        result = [page async for page in iter_keyset_pages(fetch_page, page_size=2)]

        assert result == [[1, 2], [3]]

    async def test_respects_max_items(self) -> None:
        calls: list[tuple[int | None, int]] = []

        async def fetch_page(token: int | None, limit: int) -> tuple[list[int], int | None]:
            calls.append((token, limit))
            if token is None:
                return [1, 2, 3][:limit], 3
            return [4, 5, 6][:limit], 6

        result = [page async for page in iter_keyset_pages(fetch_page, page_size=3, max_items=4)]

        assert result == [[1, 2, 3], [4]]
        assert calls == [(None, 3), (3, 1)]

    @pytest.mark.parametrize(
        ("page_size", "max_items", "message"),
        [
            (0, None, "page_size"),
            (2, -1, "max_items"),
        ],
    )
    async def test_rejects_invalid_bounds(
        self, page_size: int, max_items: int | None, message: str
    ) -> None:
        async def fetch_page(token: int | None, limit: int) -> tuple[list[int], int | None]:
            return [], token

        with pytest.raises(ValueError, match=message):
            _ = [
                page
                async for page in iter_keyset_pages(
                    fetch_page, page_size=page_size, max_items=max_items
                )
            ]
