"""LilBrotr schema fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration.harness.brotr import PgDsn, make_deployment_brotr


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr


@pytest.fixture
async def brotr(pg_dsn: PgDsn) -> AsyncIterator[Brotr]:
    """Provide a Brotr instance backed by the lilbrotr schema."""
    async for b in make_deployment_brotr(pg_dsn, "lilbrotr"):
        yield b
