"""Unit tests for services.common.queries module.

Tests the shared batch-insert helper and upsert_service_states wrapper
that are used by multiple service query modules.

Every test mocks the Brotr layer directly so no database connection is
required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.services.common.queries import (
    batched_insert,
    upsert_service_states,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def query_brotr() -> MagicMock:
    """Create a mock Brotr with all query facade methods stubbed."""
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchrow = AsyncMock(return_value={"count": 0})
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.execute = AsyncMock(return_value="DELETE 0")
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.get_service_state = AsyncMock(return_value=[])
    brotr.config.batch.max_size = 1000
    return brotr


# ============================================================================
# TestBatchedInsert
# ============================================================================


class TestBatchedInsert:
    """Tests for batched_insert() helper."""

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        """Returns 0 without calling the method when records is empty."""
        method = AsyncMock(return_value=5)
        result = await batched_insert(query_brotr, [], method)
        assert result == 0
        method.assert_not_called()

    async def test_under_limit_single_call(self, query_brotr: MagicMock) -> None:
        """Passes all records in one call when under batch limit."""
        query_brotr.config.batch.max_size = 100
        method = AsyncMock(return_value=3)

        result = await batched_insert(query_brotr, [1, 2, 3], method)

        assert result == 3
        method.assert_awaited_once_with([1, 2, 3])

    async def test_over_limit_splits(self, query_brotr: MagicMock) -> None:
        """Splits records into multiple calls when exceeding batch limit."""
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await batched_insert(query_brotr, [1, 2, 3, 4, 5], method)

        assert result == 6  # 2 + 2 + 2
        assert method.await_count == 3
        method.assert_any_await([1, 2])
        method.assert_any_await([3, 4])
        method.assert_any_await([5])

    async def test_exact_multiple(self, query_brotr: MagicMock) -> None:
        """Handles exact multiples of batch size correctly."""
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await batched_insert(query_brotr, [1, 2, 3, 4], method)

        assert result == 4
        assert method.await_count == 2


# ============================================================================
# TestUpsertServiceStates
# ============================================================================


class TestUpsertServiceStates:
    """Tests for upsert_service_states() batch splitting."""

    async def test_delegates_tobatched_insert(self, query_brotr: MagicMock) -> None:
        """Calls brotr.upsert_service_state via batched_insert."""
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        records = [MagicMock(), MagicMock()]
        result = await upsert_service_states(query_brotr, records)

        assert result == 2
        query_brotr.upsert_service_state.assert_awaited_once()

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        """Splits records exceeding batch limit."""
        query_brotr.config.batch.max_size = 2
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await upsert_service_states(query_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.upsert_service_state.await_count == 3

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        """Returns 0 for empty input."""
        result = await upsert_service_states(query_brotr, [])
        assert result == 0
        query_brotr.upsert_service_state.assert_not_awaited()
