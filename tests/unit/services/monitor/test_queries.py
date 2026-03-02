"""Unit tests for services.monitor.queries module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.monitor.queries import (
    delete_stale_checkpoints,
    fetch_relays_to_monitor,
    insert_relay_metadata,
    save_monitoring_markers,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.insert_relay_metadata = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


@pytest.fixture
def mock_monitor(query_brotr: MagicMock) -> MagicMock:
    m = MagicMock()
    m._brotr = query_brotr
    m.SERVICE_NAME = ServiceName.MONITOR
    return m


def _make_dict_row(data: dict[str, Any]) -> dict[str, Any]:
    return data


# ============================================================================
# TestDeleteStaleCheckpoints
# ============================================================================


class TestDeleteStaleCheckpoints:
    """Tests for delete_stale_checkpoints()."""

    async def test_calls_fetchval_with_correct_params(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=4)

        result = await delete_stale_checkpoints(mock_monitor)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "LIKE 'ws%'" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.MONITOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert result == 4

    async def test_returns_zero_on_none(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_stale_checkpoints(mock_monitor)

        assert result == 0


# ============================================================================
# TestFetchRelaysToMonitor
# ============================================================================


class TestFetchRelaysToMonitor:
    """Tests for fetch_relays_to_monitor()."""

    async def test_calls_fetch_with_correct_params(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        await fetch_relays_to_monitor(
            mock_monitor,
            monitored_before=1700000000,
            networks=[NetworkType.CLEARNET],
        )

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM relay r" in sql
        assert "LEFT JOIN service_state ss" in sql
        assert "service_name = $3" in sql
        assert "state_type = $4" in sql
        assert args[0][1] == [NetworkType.CLEARNET]
        assert args[0][2] == 1700000000
        assert args[0][3] == ServiceName.MONITOR
        assert args[0][4] == ServiceStateType.CHECKPOINT

    async def test_returns_relay_objects(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_to_monitor(mock_monitor, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"

    async def test_skips_invalid_urls(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        rows = [
            _make_dict_row(
                {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "not-valid", "network": "clearnet", "discovered_at": 1700000000}
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_relays_to_monitor(mock_monitor, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://valid.relay.com"

    async def test_empty_result(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await fetch_relays_to_monitor(mock_monitor, 1700000000, [NetworkType.CLEARNET])

        assert result == []


# ============================================================================
# TestInsertRelayMetadata
# ============================================================================


class TestInsertRelayMetadata:
    """Tests for insert_relay_metadata() batch splitting."""

    async def test_delegates_to_batched_insert(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.insert_relay_metadata = AsyncMock(return_value=5)

        result = await insert_relay_metadata(mock_monitor, [MagicMock(), MagicMock()])

        assert result == 5
        query_brotr.insert_relay_metadata.assert_awaited_once()

    async def test_splits_large_batch(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.config.batch.max_size = 2
        query_brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_relay_metadata(mock_monitor, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.insert_relay_metadata.await_count == 3

    async def test_empty_returns_zero(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        result = await insert_relay_metadata(mock_monitor, [])
        assert result == 0
        query_brotr.insert_relay_metadata.assert_not_awaited()


# ============================================================================
# TestSaveMonitoringMarkers
# ============================================================================


class TestSaveMonitoringMarkers:
    """Tests for save_monitoring_markers()."""

    async def test_calls_upsert_for_each_relay(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        relays = [Relay("wss://r1.example.com"), Relay("wss://r2.example.com")]
        await save_monitoring_markers(mock_monitor, relays, 1700000000)

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 2

    async def test_state_record_fields(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        relay = Relay("wss://relay.example.com")
        now = 1700000000
        await save_monitoring_markers(mock_monitor, [relay], now)

        states = query_brotr.upsert_service_state.call_args[0][0]
        state = states[0]
        assert isinstance(state, ServiceState)
        assert state.service_name == ServiceName.MONITOR
        assert state.state_type == ServiceStateType.CHECKPOINT
        assert state.state_key == relay.url
        assert state.state_value == {"timestamp": now}

    async def test_empty_relay_list_no_db_call(
        self, mock_monitor: MagicMock, query_brotr: MagicMock
    ) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=0)

        await save_monitoring_markers(mock_monitor, [], 1700000000)

        query_brotr.upsert_service_state.assert_not_awaited()
