"""Unit tests for services.finder.queries module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.types import EventRelayCursor
from bigbrotr.services.finder.queries import (
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_event_relay_cursors,
    load_api_checkpoints,
    save_api_checkpoints,
    save_event_relay_cursor,
    scan_event_relay,
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
    brotr.get_service_state = AsyncMock(return_value=[])
    brotr.config.batch.max_size = 1000
    return brotr


def _make_dict_row(data: dict[str, Any]) -> dict[str, Any]:
    return data


# ============================================================================
# TestDeleteStaleCursors
# ============================================================================


class TestDeleteStaleCursors:
    """Tests for delete_stale_cursors()."""

    async def test_calls_fetchval_with_correct_params(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=3)

        result = await delete_stale_cursors(query_brotr)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.FINDER
        assert args[0][2] == ServiceStateType.CURSOR
        assert result == 3

    async def test_returns_zero_on_none(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_stale_cursors(query_brotr)

        assert result == 0


# ============================================================================
# TestDeleteStaleApiCheckpoints
# ============================================================================


class TestDeleteStaleApiCheckpoints:
    """Tests for delete_stale_api_checkpoints()."""

    async def test_deletes_inactive_sources(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=2)

        result = await delete_stale_api_checkpoints(
            query_brotr, ["https://active.example.com"]
        )

        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "NOT (state_key = ANY($3::text[]))" in sql
        assert args[0][1] == ServiceName.FINDER
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == ["https://active.example.com"]
        assert result == 2

    async def test_returns_zero_on_none(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_stale_api_checkpoints(query_brotr, [])

        assert result == 0


# ============================================================================
# TestFetchEventRelayCursors
# ============================================================================


class TestFetchEventRelayCursors:
    """Tests for fetch_event_relay_cursors()."""

    async def test_returns_cursor_for_relay_with_state(self, query_brotr: MagicMock) -> None:
        rows = [
            _make_dict_row(
                {"url": "wss://relay.com", "seen_at": "1700000000", "event_id": "ab" * 32}
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_event_relay_cursors(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.relay_url == "wss://relay.com"
        assert cursor.seen_at == 1700000000
        assert cursor.event_id == bytes.fromhex("ab" * 32)

    async def test_returns_empty_cursor_for_relay_without_state(
        self, query_brotr: MagicMock
    ) -> None:
        rows = [
            _make_dict_row({"url": "wss://new.relay.com", "seen_at": None, "event_id": None}),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_event_relay_cursors(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.relay_url == "wss://new.relay.com"
        assert cursor.seen_at is None
        assert cursor.event_id is None

    async def test_invalid_cursor_data_falls_back_to_empty(
        self, query_brotr: MagicMock
    ) -> None:
        rows = [
            _make_dict_row({"url": "wss://corrupt.com", "seen_at": "100", "event_id": "not-hex"}),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_event_relay_cursors(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.seen_at is None
        assert cursor.event_id is None

    async def test_query_uses_left_join(self, query_brotr: MagicMock) -> None:
        await fetch_event_relay_cursors(query_brotr)

        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "LEFT JOIN service_state" in sql
        assert "FROM relay" in sql

    async def test_empty_database(self, query_brotr: MagicMock) -> None:
        result = await fetch_event_relay_cursors(query_brotr)

        assert result == []


# ============================================================================
# TestScanEventRelay
# ============================================================================


class TestScanEventRelay:
    """Tests for scan_event_relay()."""

    async def test_scan_with_cursor(self, query_brotr: MagicMock) -> None:
        event_id = b"\xab" * 32
        cursor = EventRelayCursor(
            relay_url="wss://source.relay.com",
            seen_at=1700000000,
            event_id=event_id,
        )
        await scan_event_relay(query_brotr, cursor, limit=500)

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM event e" in sql
        assert "event_relay er" in sql
        assert "relay_url = $1" in sql
        assert "IS NULL OR (er.seen_at, e.id) >" in sql
        assert "LIMIT $4" in sql
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] == 1700000000
        assert args[0][3] == event_id
        assert args[0][4] == 500

    async def test_scan_no_cursor(self, query_brotr: MagicMock) -> None:
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        await scan_event_relay(query_brotr, cursor, limit=100)

        args = query_brotr.fetch.call_args
        assert args[0][2] is None
        assert args[0][3] is None

    async def test_scan_empty(self, query_brotr: MagicMock) -> None:
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        result = await scan_event_relay(query_brotr, cursor, limit=100)

        assert result == []


# ============================================================================
# TestLoadApiCheckpoints
# ============================================================================


class TestLoadApiCheckpoints:
    """Tests for load_api_checkpoints()."""

    async def test_happy_path(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {"timestamp": 1700001000}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == {
            "https://api1.example.com": 1700000000,
            "https://api2.example.com": 1700001000,
        }

    async def test_skips_malformed(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == {"https://api1.example.com": 1700000000}

    async def test_empty_urls(self, query_brotr: MagicMock) -> None:
        result = await load_api_checkpoints(query_brotr, [])

        assert result == {}

    async def test_no_rows(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(return_value=[])
        urls = ["https://api.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == {}


# ============================================================================
# TestSaveApiCheckpoints
# ============================================================================


class TestSaveApiCheckpoints:
    """Tests for save_api_checkpoints()."""

    async def test_upserts_checkpoint_per_url(self, query_brotr: MagicMock) -> None:
        state = {
            "https://api1.example.com": 1700000000,
            "https://api2.example.com": 1700001000,
        }
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        await save_api_checkpoints(query_brotr, state)

        query_brotr.upsert_service_state.assert_awaited_once()
        records: list[ServiceState] = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        urls = {r.state_key for r in records}
        assert urls == {"https://api1.example.com", "https://api2.example.com"}
        for r in records:
            assert r.service_name == ServiceName.FINDER
            assert r.state_type == ServiceStateType.CHECKPOINT
            assert r.state_value == {"timestamp": state[r.state_key]}


# ============================================================================
# TestSaveEventRelayCursor
# ============================================================================


class TestSaveEventRelayCursor:
    """Tests for save_event_relay_cursor()."""

    async def test_happy_path(self, query_brotr: MagicMock) -> None:
        cursor = EventRelayCursor(
            relay_url="wss://relay.example.com",
            seen_at=1700000200,
            event_id=b"\xab" * 32,
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        await save_event_relay_cursor(query_brotr, cursor)

        query_brotr.upsert_service_state.assert_awaited_once()
        records: list[ServiceState] = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        state = records[0]
        assert state.service_name == ServiceName.FINDER
        assert state.state_type == ServiceStateType.CURSOR
        assert state.state_key == "wss://relay.example.com"
        assert state.state_value["seen_at"] == 1700000200
        assert state.state_value["event_id"] == (b"\xab" * 32).hex()

    async def test_noop_when_blank(self, query_brotr: MagicMock) -> None:
        cursor = EventRelayCursor(relay_url="wss://relay.example.com")
        query_brotr.upsert_service_state = AsyncMock(return_value=0)

        await save_event_relay_cursor(query_brotr, cursor)

        query_brotr.upsert_service_state.assert_not_awaited()
