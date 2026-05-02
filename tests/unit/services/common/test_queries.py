"""Unit tests for services.common.discovery_queries module.

Tests the shared candidate-insert helpers used by multiple service query modules.

Every test mocks the Brotr layer directly so no database connection is
required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.discovery_queries import insert_relays_as_candidates


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
# Helpers
# ============================================================================


def _mock_relay(
    url: str = "wss://relay.example.com",
    network: NetworkType = NetworkType.CLEARNET,
) -> MagicMock:
    relay = MagicMock()
    relay.url = url
    relay.network = network
    return relay


def _row(data: dict[str, Any]) -> dict[str, Any]:
    return data


# ============================================================================
# TestInsertRelaysAsCandidates
# ============================================================================


class TestInsertRelaysAsCandidates:
    async def test_filters_then_upserts(self, query_brotr: MagicMock) -> None:
        relay = _mock_relay()
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": "wss://relay.example.com",
                        "relay_exists": False,
                        "state_value": None,
                    }
                )
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.fetch.assert_awaited_once()
        assert "unnest($1::text[])" in query_brotr.fetch.call_args[0][0]
        assert "LEFT JOIN service_state" in query_brotr.fetch.call_args[0][0]
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        record = records[0]
        assert record.owner == ServiceName.VALIDATOR
        assert record.state_type == ServiceStateType.CHECKPOINT
        assert record.state_key == "wss://relay.example.com"
        assert record.state_value["failures"] == 0
        assert record.state_value["network"] == "clearnet"
        assert "timestamp" in record.state_value
        assert result == 1

    async def test_rounds_fractional_candidate_timestamp_up(
        self,
        query_brotr: MagicMock,
    ) -> None:
        relay = _mock_relay()
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": relay.url,
                        "relay_exists": False,
                        "state_value": None,
                    }
                )
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        with patch("bigbrotr.services.common.discovery_queries.time.time", return_value=1000.1):
            result = await insert_relays_as_candidates(query_brotr, [relay])

        record = query_brotr.upsert_service_state.call_args[0][0][0]
        assert record.state_value["timestamp"] == 1001
        assert result == 1

    async def test_all_filtered_out(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": "wss://relay.example.com",
                        "relay_exists": True,
                        "state_value": None,
                    }
                )
            ]
        )
        result = await insert_relays_as_candidates(query_brotr, [_mock_relay()])
        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_input(self, query_brotr: MagicMock) -> None:
        result = await insert_relays_as_candidates(query_brotr, [])
        query_brotr.fetch.assert_not_awaited()
        assert result == 0

    async def test_batching(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        relays = [_mock_relay(f"wss://r{i}.example.com") for i in range(3)]
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": relay.url,
                        "relay_exists": False,
                        "state_value": None,
                    }
                )
                for relay in relays
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(side_effect=[2, 1])

        result = await insert_relays_as_candidates(query_brotr, relays)

        assert query_brotr.upsert_service_state.await_count == 2
        assert result == 3

    async def test_deduplicates_new_input_relays_preserving_first_seen_order(
        self, query_brotr: MagicMock
    ) -> None:
        relays = [
            _mock_relay("wss://dup.example.com"),
            _mock_relay("wss://second.example.com"),
            _mock_relay("wss://dup.example.com"),
        ]
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": "wss://second.example.com",
                        "relay_exists": False,
                        "state_value": None,
                    }
                ),
                _row(
                    {
                        "url": "wss://dup.example.com",
                        "relay_exists": False,
                        "state_value": None,
                    }
                ),
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        result = await insert_relays_as_candidates(query_brotr, relays)

        query_brotr.upsert_service_state.assert_awaited_once()
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert [record.state_key for record in records] == [
            "wss://dup.example.com",
            "wss://second.example.com",
        ]
        assert result == 2

    async def test_invalid_persisted_candidate_does_not_block_rediscovery(
        self, query_brotr: MagicMock
    ) -> None:
        relay = _mock_relay()
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "url": relay.url,
                        "relay_exists": False,
                        "state_value": {
                            "timestamp": 10,
                            "failures": 0,
                            "network": "tor",
                        },
                    }
                )
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.upsert_service_state.assert_awaited_once()
        record = query_brotr.upsert_service_state.call_args.args[0][0]
        assert record.state_key == relay.url
        assert record.state_value["network"] == "clearnet"
        assert result == 1
