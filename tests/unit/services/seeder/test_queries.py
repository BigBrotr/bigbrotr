"""Unit tests for services.seeder.queries module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.services.seeder.queries import insert_relays


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.insert_relay = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


@pytest.fixture
def mock_seeder(query_brotr: MagicMock) -> MagicMock:
    s = MagicMock()
    s._brotr = query_brotr
    return s


# ============================================================================
# TestInsertRelays
# ============================================================================


class TestInsertRelays:
    """Tests for insert_relays() batch splitting."""

    async def test_delegates_to_insert_relay(
        self, mock_seeder: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.insert_relay = AsyncMock(return_value=2)
        query_brotr.config.batch.max_size = 1

        relays = [Relay("wss://a.example.com"), Relay("wss://b.example.com")]
        result = await insert_relays(mock_seeder, relays)

        assert result == 4  # 2 batches × 2 each
        assert query_brotr.insert_relay.await_count == 2

    async def test_empty_returns_zero(
        self, mock_seeder: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await insert_relays(mock_seeder, [])

        assert result == 0
        query_brotr.insert_relay.assert_not_awaited()

    async def test_single_batch_when_under_limit(
        self, mock_seeder: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.insert_relay = AsyncMock(return_value=3)
        relays = [
            Relay("wss://a.example.com"),
            Relay("wss://b.example.com"),
            Relay("wss://c.example.com"),
        ]

        result = await insert_relays(mock_seeder, relays)

        assert result == 3
        query_brotr.insert_relay.assert_awaited_once()
