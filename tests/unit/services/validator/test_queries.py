"""Unit tests for services.validator.queries module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.types import CandidateCheckpoint
from bigbrotr.services.validator.queries import (
    count_candidates,
    delete_exhausted_candidates,
    delete_promoted_candidates,
    fail_candidates,
    fetch_candidates,
    insert_relays_as_candidates,
    promote_candidates,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchrow = AsyncMock(return_value={"count": 0})
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.insert_relay = AsyncMock(return_value=0)
    brotr.delete_service_state = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


@pytest.fixture
def mock_validator(query_brotr: MagicMock) -> MagicMock:
    v = MagicMock()
    v._brotr = query_brotr
    v._config.cleanup.max_failures = 5
    return v


def _make_dict_row(data: dict[str, Any]) -> dict[str, Any]:
    return data


def _make_mock_relay(
    url: str = "wss://relay.example.com",
    network_value: str = "clearnet",
) -> MagicMock:
    relay = MagicMock()
    relay.url = url
    relay.network = MagicMock(value=network_value)
    return relay


# ============================================================================
# TestInsertCandidates
# ============================================================================


class TestInsertCandidates:
    """Tests for insert_relays_as_candidates()."""

    async def test_filters_then_upserts(self, query_brotr: MagicMock) -> None:
        """Filters new relays internally, then upserts only new ones."""
        relay = _make_mock_relay()
        query_brotr.fetch = AsyncMock(
            return_value=[_make_dict_row({"url": "wss://relay.example.com"})]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "unnest($1::text[])" in sql

        query_brotr.upsert_service_state.assert_awaited_once()
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        record = records[0]
        assert record.service_name == ServiceName.VALIDATOR
        assert record.state_type == ServiceStateType.CHECKPOINT
        assert record.state_key == "wss://relay.example.com"
        assert record.state_value["failures"] == 0
        assert record.state_value["network"] == "clearnet"
        assert "timestamp" in record.state_value
        assert result == 1

    async def test_all_filtered_out(self, query_brotr: MagicMock) -> None:
        """Returns 0 when all relays already exist."""
        relay = _make_mock_relay()
        query_brotr.fetch = AsyncMock(return_value=[])

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_iterable(self, query_brotr: MagicMock) -> None:
        """Does not call fetch or upsert when given an empty iterable."""
        result = await insert_relays_as_candidates(query_brotr, [])

        query_brotr.fetch.assert_not_awaited()
        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_batching_large_input(self, query_brotr: MagicMock) -> None:
        """Splits into batches when relays exceed batch.max_size."""
        query_brotr.config.batch.max_size = 2
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
            _make_mock_relay("wss://r3.example.com"),
        ]
        query_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"url": "wss://r1.example.com"}),
                _make_dict_row({"url": "wss://r2.example.com"}),
                _make_dict_row({"url": "wss://r3.example.com"}),
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(side_effect=[2, 1])

        result = await insert_relays_as_candidates(query_brotr, relays)

        assert query_brotr.upsert_service_state.await_count == 2
        assert result == 3


# ============================================================================
# TestDeletePromotedCandidates
# ============================================================================


class TestDeletePromotedCandidates:
    """Tests for delete_promoted_candidates()."""

    async def test_calls_fetchval_with_correct_params(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=2)

        result = await delete_promoted_candidates(mock_validator)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "EXISTS" in sql
        assert "FROM relay r" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert result == 2

    async def test_returns_zero_when_none_deleted(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_promoted_candidates(mock_validator)

        assert result == 0


# ============================================================================
# TestDeleteExhaustedCandidates
# ============================================================================


class TestDeleteExhaustedCandidates:
    """Tests for delete_exhausted_candidates()."""

    async def test_calls_fetchval_with_correct_params(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=3)

        result = await delete_exhausted_candidates(mock_validator)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "failures" in sql
        assert ">= $3" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == 5  # max_failures from mock_validator._config
        assert result == 3

    async def test_returns_zero_when_none_deleted(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=0)

        result = await delete_exhausted_candidates(mock_validator)

        assert result == 0


# ============================================================================
# TestCountCandidates
# ============================================================================


class TestCountCandidates:
    """Tests for count_candidates()."""

    async def test_calls_fetchrow_with_correct_params(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchrow = AsyncMock(return_value={"count": 15})

        result = await count_candidates(
            mock_validator,
            networks=[NetworkType.CLEARNET, NetworkType.TOR],
            attempted_before=1700000000,
        )

        query_brotr.fetchrow.assert_awaited_once()
        args = query_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "failures" in sql
        assert "timestamp" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == [NetworkType.CLEARNET, NetworkType.TOR]
        assert args[0][4] == 1700000000
        assert result == 15

    async def test_returns_zero_when_row_is_none(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchrow = AsyncMock(return_value=None)

        result = await count_candidates(mock_validator, [NetworkType.CLEARNET], 1700000000)

        assert result == 0


# ============================================================================
# TestFetchCandidates
# ============================================================================


class TestFetchCandidates:
    """Tests for fetch_candidates()."""

    async def test_calls_fetch_with_correct_params(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        await fetch_candidates(
            mock_validator,
            networks=[NetworkType.CLEARNET],
            attempted_before=1700000000,
            limit=50,
        )

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "state_key, state_value" in sql
        assert "FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "failures" in sql
        assert "timestamp" in sql
        assert "LIMIT $5" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == [NetworkType.CLEARNET]
        assert args[0][4] == 1700000000
        assert args[0][5] == 50

    async def test_returns_candidate_checkpoint_objects(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        row = _make_dict_row(
            {
                "state_key": "wss://relay.example.com",
                "state_value": {"failures": 0, "network": "clearnet", "timestamp": 1700000000},
            }
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_candidates(mock_validator, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert isinstance(result[0], CandidateCheckpoint)
        assert result[0].key == "wss://relay.example.com"
        assert result[0].timestamp == 1700000000
        assert result[0].network == NetworkType.CLEARNET
        assert result[0].failures == 0

    async def test_skips_invalid_network(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        rows = [
            _make_dict_row(
                {
                    "state_key": "wss://relay.example.com",
                    "state_value": {"failures": 0, "network": "clearnet", "timestamp": 1700000000},
                }
            ),
            _make_dict_row(
                {
                    "state_key": "wss://bad.example.com",
                    "state_value": {
                        "failures": 0,
                        "network": "invalid_net",
                        "timestamp": 1700000000,
                    },
                }
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_candidates(mock_validator, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert result[0].key == "wss://relay.example.com"

    async def test_empty_result(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await fetch_candidates(mock_validator, [NetworkType.CLEARNET], 1700000000, 50)

        assert result == []


# ============================================================================
# TestPromoteCandidates
# ============================================================================


class TestPromoteCandidates:
    """Tests for promote_candidates()."""

    async def test_inserts_relays_and_deletes_candidates(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        candidate = CandidateCheckpoint(
            key="wss://promoted.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
            failures=0,
        )
        query_brotr.insert_relay = AsyncMock(return_value=1)
        query_brotr.delete_service_state = AsyncMock(return_value=1)

        result = await promote_candidates(mock_validator, [candidate])

        query_brotr.insert_relay.assert_awaited_once()
        relays = query_brotr.insert_relay.call_args[0][0]
        assert len(relays) == 1
        assert relays[0].url == "wss://promoted.example.com"
        query_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR],
            [ServiceStateType.CHECKPOINT],
            ["wss://promoted.example.com"],
        )
        assert result == 1

    async def test_empty_candidate_list(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await promote_candidates(mock_validator, [])

        query_brotr.insert_relay.assert_not_awaited()
        assert result == 0

    async def test_multiple_candidates(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        candidates = [
            CandidateCheckpoint(
                key="wss://r1.example.com",
                timestamp=1700000000,
                network=NetworkType.CLEARNET,
                failures=0,
            ),
            CandidateCheckpoint(
                key="wss://r2.example.com",
                timestamp=1700000000,
                network=NetworkType.CLEARNET,
                failures=1,
            ),
        ]
        query_brotr.insert_relay = AsyncMock(return_value=2)
        query_brotr.delete_service_state = AsyncMock(return_value=2)

        result = await promote_candidates(mock_validator, candidates)

        relays = query_brotr.insert_relay.call_args[0][0]
        assert [r.url for r in relays] == ["wss://r1.example.com", "wss://r2.example.com"]
        query_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR, ServiceName.VALIDATOR],
            [ServiceStateType.CHECKPOINT, ServiceStateType.CHECKPOINT],
            ["wss://r1.example.com", "wss://r2.example.com"],
        )
        assert result == 2


# ============================================================================
# TestFailCandidates
# ============================================================================


class TestFailCandidates:
    """Tests for fail_candidates()."""

    async def test_increments_failures(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        candidate = CandidateCheckpoint(
            key="wss://bad.example.com",
            timestamp=1700000000,
            network=NetworkType.CLEARNET,
            failures=2,
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await fail_candidates(mock_validator, [candidate])

        query_brotr.upsert_service_state.assert_awaited_once()
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        assert records[0].state_value["failures"] == 3
        assert records[0].state_key == "wss://bad.example.com"
        assert result == 1

    async def test_empty_list(
        self, mock_validator: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await fail_candidates(mock_validator, [])

        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0
