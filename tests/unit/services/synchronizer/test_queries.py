"""Unit tests for services.synchronizer.queries module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.synchronizer.queries import (
    delete_stale_cursors,
    insert_event_relays,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.insert_event_relay = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


@pytest.fixture
def mock_synchronizer(query_brotr: MagicMock) -> MagicMock:
    s = MagicMock()
    s._brotr = query_brotr
    s.SERVICE_NAME = ServiceName.SYNCHRONIZER
    return s


# ============================================================================
# TestDeleteStaleCursors
# ============================================================================


class TestDeleteStaleCursors:
    """Tests for delete_stale_cursors()."""

    async def test_calls_fetchval_with_correct_params(
        self, mock_synchronizer: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=5)

        result = await delete_stale_cursors(mock_synchronizer)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.SYNCHRONIZER
        assert args[0][2] == ServiceStateType.CURSOR
        assert result == 5

    async def test_returns_zero_on_none(
        self, mock_synchronizer: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_stale_cursors(mock_synchronizer)

        assert result == 0


# ============================================================================
# TestInsertEventRelays
# ============================================================================


class TestInsertEventRelays:
    """Tests for insert_event_relays() batch splitting."""

    async def test_delegates_to_insert_event_relay(self, query_brotr: MagicMock) -> None:
        query_brotr.insert_event_relay = AsyncMock(return_value=3)

        result = await insert_event_relays(query_brotr, [MagicMock(), MagicMock(), MagicMock()])

        assert result == 3
        query_brotr.insert_event_relay.assert_awaited_once()

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        result = await insert_event_relays(query_brotr, [])

        assert result == 0
        query_brotr.insert_event_relay.assert_not_awaited()

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        query_brotr.insert_event_relay = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_event_relays(query_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.insert_event_relay.await_count == 3
