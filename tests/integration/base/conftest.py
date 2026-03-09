"""Base schema fixture (uses bigbrotr deployment)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import make_brotr


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr


@pytest.fixture
async def brotr(pg_dsn: dict[str, str | int]) -> AsyncIterator[Brotr]:
    """Provide a Brotr instance backed by the bigbrotr (base) schema."""
    async for b in make_brotr(pg_dsn, "bigbrotr"):
        yield b
