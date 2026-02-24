"""BigBrotr schema fixture."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from tests.integration.conftest import make_brotr


@pytest.fixture
async def brotr(pg_dsn: dict[str, str | int]) -> Brotr:
    """Provide a Brotr instance backed by the bigbrotr schema."""
    async for b in make_brotr(pg_dsn, "bigbrotr"):
        yield b
