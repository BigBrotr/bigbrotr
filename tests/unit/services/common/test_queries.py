"""Unit tests for services.common.queries module.

Tests the domain SQL query functions that centralize database access for
BigBrotr services.  Each function accepts a ``Brotr`` instance and delegates
to one of its query facade methods (fetch, fetchrow, fetchval, execute,
upsert_service_state, transaction).

Every test mocks the Brotr layer directly so no database connection is
required.  Assertions verify:

- The correct Brotr method is called.
- The SQL contains expected key fragments.
- Parameters are passed in the correct position.
- The return value is properly transformed.
- Edge cases (empty results, None returns) are handled.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.queries import (
    _batched_insert,
    cleanup_stale,
    count_candidates,
    delete_exhausted_candidates,
    fetch_candidates,
    fetch_event_relay_cursors,
    fetch_relays,
    fetch_relays_to_monitor,
    insert_event_relays,
    insert_relay_metadata,
    insert_relays,
    insert_relays_as_candidates,
    promote_candidates,
    scan_event,
    scan_event_relay,
    upsert_service_states,
)
from bigbrotr.services.common.types import Candidate, EventCursor, EventRelayCursor


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

    # Transaction context manager
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.execute = AsyncMock()

    mock_tx = AsyncMock()
    mock_tx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_tx.__aexit__ = AsyncMock(return_value=False)
    brotr.transaction = MagicMock(return_value=mock_tx)

    # Expose mock_conn for assertions in promote_candidates tests
    brotr._mock_conn = mock_conn

    return brotr


def _make_mock_relay(
    url: str = "wss://relay.example.com",
    network_value: str = "clearnet",
    discovered_at: int = 1700000000,
) -> MagicMock:
    """Create a mock Relay object with to_db_params support."""
    relay = MagicMock()
    relay.url = url
    relay.network = MagicMock(value=network_value)

    params = MagicMock()
    params.url = url
    params.network = network_value
    params.discovered_at = discovered_at
    relay.to_db_params = MagicMock(return_value=params)

    return relay


def _make_dict_row(data: dict[str, Any]) -> dict[str, Any]:
    """Create a dict usable as a mock asyncpg Record row.

    The query functions access rows via ``row["key"]`` and call ``dict(row)``.
    Plain dicts satisfy both interfaces.
    """
    return data


# ============================================================================
# TestGetAllRelays
# ============================================================================


class TestFetchAllRelays:
    """Tests for fetch_relays()."""

    async def test_calls_fetch(self, query_brotr: MagicMock) -> None:
        """Calls brotr.fetch with a query selecting url, network, discovered_at."""
        await fetch_relays(query_brotr)

        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "url" in sql
        assert "network" in sql
        assert "discovered_at" in sql
        assert "FROM relay" in sql

    async def test_returns_relay_objects(self, query_brotr: MagicMock) -> None:
        """Returns a list of Relay domain objects."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays(query_brotr)

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"
        assert result[0].network.value == "clearnet"

    async def test_skips_invalid_urls(self, query_brotr: MagicMock) -> None:
        """Skips rows with invalid URLs instead of raising."""
        rows = [
            _make_dict_row(
                {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "not-a-valid-url", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "wss://also.valid.com", "network": "clearnet", "discovered_at": 1700000001}
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_relays(query_brotr)

        assert len(result) == 2
        assert result[0].url == "wss://valid.relay.com"
        assert result[1].url == "wss://also.valid.com"

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        """Returns an empty list when no relays exist."""
        result = await fetch_relays(query_brotr)

        assert result == []


# ============================================================================
# TestFetchEventRelayCursors
# ============================================================================


class TestFetchEventRelayCursors:
    """Tests for fetch_event_relay_cursors()."""

    async def test_returns_cursor_for_relay_with_state(self, query_brotr: MagicMock) -> None:
        """Relay with stored cursor returns populated EventRelayCursor."""
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
        """Relay without stored cursor returns EventRelayCursor with None fields."""
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

    async def test_mixed_relays_with_and_without_cursors(self, query_brotr: MagicMock) -> None:
        """Mix of relays with and without stored cursors."""
        rows = [
            _make_dict_row(
                {"url": "wss://has-cursor.com", "seen_at": "100", "event_id": "cd" * 32}
            ),
            _make_dict_row({"url": "wss://no-cursor.com", "seen_at": None, "event_id": None}),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_event_relay_cursors(query_brotr)

        assert len(result) == 2
        by_url = {c.relay_url: c for c in result}
        assert by_url["wss://has-cursor.com"].seen_at == 100
        assert by_url["wss://no-cursor.com"].seen_at is None

    async def test_invalid_cursor_data_falls_back_to_empty(self, query_brotr: MagicMock) -> None:
        """Corrupt cursor data (non-hex event_id) falls back to empty cursor."""
        rows = [
            _make_dict_row({"url": "wss://corrupt.com", "seen_at": "100", "event_id": "not-hex"}),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_event_relay_cursors(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.seen_at is None
        assert cursor.event_id is None

    async def test_empty_database(self, query_brotr: MagicMock) -> None:
        """Empty relay table returns empty list."""
        result = await fetch_event_relay_cursors(query_brotr)

        assert result == []

    async def test_query_uses_left_join(self, query_brotr: MagicMock) -> None:
        """Query uses LEFT JOIN on service_state."""
        await fetch_event_relay_cursors(query_brotr)

        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "LEFT JOIN service_state" in sql
        assert "FROM relay" in sql


# ============================================================================
# TestFilterNewRelayUrls
# ============================================================================


# ============================================================================
# TestFetchRelaysToMonitor
# ============================================================================


class TestFetchRelaysToMonitor:
    """Tests for fetch_relays_to_monitor()."""

    async def test_calls_fetch_with_correct_params(self, query_brotr: MagicMock) -> None:
        """Passes networks, monitored_before, ServiceName.MONITOR, ServiceStateType.CHECKPOINT."""
        await fetch_relays_to_monitor(
            query_brotr,
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

    async def test_returns_relay_objects(self, query_brotr: MagicMock) -> None:
        """Returns Relay domain objects."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"
        assert result[0].network.value == "clearnet"

    async def test_skips_invalid_urls(self, query_brotr: MagicMock) -> None:
        """Skips rows with invalid URLs instead of raising."""
        rows = [
            _make_dict_row(
                {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "not-valid", "network": "clearnet", "discovered_at": 1700000000}
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://valid.relay.com"

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        """Returns an empty list when no relays are due."""
        result = await fetch_relays_to_monitor(query_brotr, 1700000000, [NetworkType.CLEARNET])

        assert result == []


# ============================================================================
# TestFetchEventTagvalues
# ============================================================================


class TestScanEventRelay:
    """Tests for scan_event_relay()."""

    async def test_scan_with_cursor(self, query_brotr: MagicMock) -> None:
        """Passes cursor fields and limit to the SQL query."""
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
        assert "e.id ASC" in sql
        assert "LIMIT $4" in sql
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] == 1700000000
        assert args[0][3] == event_id
        assert args[0][4] == 500

    async def test_scan_no_cursor(self, query_brotr: MagicMock) -> None:
        """Passes None for cursor fields when starting fresh."""
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        await scan_event_relay(query_brotr, cursor, limit=100)

        args = query_brotr.fetch.call_args
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] is None
        assert args[0][3] is None

    async def test_scan_returns_dicts(self, query_brotr: MagicMock) -> None:
        """Returns dicts with all event columns plus seen_at."""
        event_id = b"\xab" * 32
        row = _make_dict_row(
            {
                "event_id": event_id,
                "pubkey": b"\xcd" * 32,
                "created_at": 1700000001,
                "kind": 1,
                "tags": "[]",
                "content": "hello",
                "sig": b"\xef" * 64,
                "tagvalues": ["r:wss://relay.example.com", "e:" + "a" * 64],
                "seen_at": 1700000001,
            }
        )
        query_brotr.fetch = AsyncMock(return_value=[row])
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")

        result = await scan_event_relay(query_brotr, cursor, limit=100)

        assert len(result) == 1
        assert result[0]["tagvalues"] == ["r:wss://relay.example.com", "e:" + "a" * 64]
        assert result[0]["seen_at"] == 1700000001
        assert result[0]["event_id"] == event_id

    async def test_scan_empty(self, query_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        result = await scan_event_relay(query_brotr, cursor, limit=100)

        assert result == []


class TestScanEvent:
    """Tests for scan_event()."""

    async def test_scan_with_cursor(self, query_brotr: MagicMock) -> None:
        """Passes cursor fields and limit to the SQL query."""
        event_id = b"\xab" * 32
        cursor = EventCursor(created_at=1700000000, event_id=event_id)
        await scan_event(query_brotr, cursor, limit=500)

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM event" in sql
        assert "IS NULL OR (created_at, id) >" in sql
        assert "id ASC" in sql
        assert "LIMIT $3" in sql
        assert args[0][1] == 1700000000
        assert args[0][2] == event_id
        assert args[0][3] == 500

    async def test_scan_no_cursor(self, query_brotr: MagicMock) -> None:
        """Passes None for cursor fields when starting fresh."""
        cursor = EventCursor()
        await scan_event(query_brotr, cursor, limit=100)

        args = query_brotr.fetch.call_args
        assert args[0][1] is None
        assert args[0][2] is None

    async def test_scan_empty(self, query_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        cursor = EventCursor()
        result = await scan_event(query_brotr, cursor, limit=100)

        assert result == []


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

        # _filter_new_relays called via brotr.fetch
        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "unnest($1::text[])" in sql

        # upsert_service_state called with the filtered relay
        query_brotr.upsert_service_state.assert_awaited_once()
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        record = records[0]
        assert record.service_name == ServiceName.VALIDATOR
        assert record.state_type == ServiceStateType.CANDIDATE
        assert record.state_key == "wss://relay.example.com"
        assert record.state_value == {"network": "clearnet", "failures": 0}
        assert result == 1

    async def test_multiple_relays_partially_new(self, query_brotr: MagicMock) -> None:
        """Only inserts relays that pass the filter."""
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
            _make_mock_relay("ws://r3.onion", network_value="tor"),
        ]
        # Only r1 and r3 are new
        query_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"url": "wss://r1.example.com"}),
                _make_dict_row({"url": "ws://r3.onion"}),
            ]
        )
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        result = await insert_relays_as_candidates(query_brotr, relays)

        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        assert result == 2
        keys = {r.state_key for r in records}
        assert keys == {"wss://r1.example.com", "ws://r3.onion"}

    async def test_all_filtered_out(self, query_brotr: MagicMock) -> None:
        """Returns 0 when all relays already exist (filter returns empty)."""
        relay = _make_mock_relay()
        query_brotr.fetch = AsyncMock(return_value=[])

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_iterable(self, query_brotr: MagicMock) -> None:
        """Does not call fetch or upsert_service_state when given an empty iterable."""
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

        assert query_brotr.upsert_service_state.await_count == 2  # 2 + 1
        assert result == 3


# ============================================================================
# TestCountCandidates
# ============================================================================


class TestCountCandidates:
    """Tests for count_candidates()."""

    async def test_calls_fetchrow_with_correct_params(self, query_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, and networks."""
        query_brotr.fetchrow = AsyncMock(return_value={"count": 15})

        result = await count_candidates(
            query_brotr, networks=[NetworkType.CLEARNET, NetworkType.TOR]
        )

        query_brotr.fetchrow.assert_awaited_once()
        args = query_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert args[0][3] == [NetworkType.CLEARNET, NetworkType.TOR]
        assert result == 15

    async def test_returns_zero_when_row_is_none(self, query_brotr: MagicMock) -> None:
        """Returns 0 when fetchrow returns None."""
        query_brotr.fetchrow = AsyncMock(return_value=None)

        result = await count_candidates(query_brotr, [NetworkType.CLEARNET])

        assert result == 0


# ============================================================================
# TestFetchCandidates
# ============================================================================


class TestFetchCandidates:
    """Tests for fetch_candidates()."""

    async def test_calls_fetch_with_correct_params(self, query_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, networks, timestamp, limit."""
        await fetch_candidates(
            query_brotr,
            networks=[NetworkType.CLEARNET],
            updated_before=1700000000,
            limit=50,
        )

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "state_key, state_value" in sql
        assert "FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "updated_at < $4" in sql
        assert "LIMIT $5" in sql
        # Positional params
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert args[0][3] == [NetworkType.CLEARNET]
        assert args[0][4] == 1700000000
        assert args[0][5] == 50

    async def test_returns_candidate_objects(self, query_brotr: MagicMock) -> None:
        """Returns Candidate domain objects constructed from rows."""
        row = _make_dict_row(
            {
                "state_key": "wss://relay.example.com",
                "state_value": {"failures": 0, "network": "clearnet"},
            }
        )
        query_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert str(result[0].relay.url) == "wss://relay.example.com"
        assert result[0].failures == 0

    async def test_skips_invalid_urls(self, query_brotr: MagicMock) -> None:
        """Skips rows with invalid relay URLs."""
        rows = [
            _make_dict_row(
                {
                    "state_key": "wss://relay.example.com",
                    "state_value": {"failures": 0, "network": "clearnet"},
                }
            ),
            _make_dict_row(
                {
                    "state_key": "not-a-url",
                    "state_value": {"failures": 0, "network": "clearnet"},
                }
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert str(result[0].relay.url) == "wss://relay.example.com"

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        """Returns an empty list when no candidates match."""
        result = await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert result == []


# ============================================================================
# TestDeleteExhaustedCandidates
# ============================================================================


class TestDeleteExhaustedCandidates:
    """Tests for delete_exhausted_candidates()."""

    async def test_calls_fetchval_with_correct_params(self, query_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, and max_failures."""
        query_brotr.fetchval = AsyncMock(return_value=3)

        result = await delete_exhausted_candidates(query_brotr, max_failures=5)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "failures" in sql
        assert ">= $3" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert args[0][3] == 5
        assert result == 3

    async def test_returns_zero_when_none_deleted(self, query_brotr: MagicMock) -> None:
        """Returns 0 when no rows are deleted."""
        query_brotr.fetchval = AsyncMock(return_value=0)

        result = await delete_exhausted_candidates(query_brotr, max_failures=3)

        assert result == 0


# ============================================================================
# TestPromoteCandidates
# ============================================================================


class TestPromoteCandidates:
    """Tests for promote_candidates()."""

    async def test_inserts_relays_and_deletes_candidates(self, query_brotr: MagicMock) -> None:
        """Calls insert_relay then delete_service_state."""
        relay = _make_mock_relay("wss://promoted.example.com")
        candidate = Candidate(relay=relay, failures=0)
        query_brotr.insert_relay = AsyncMock(return_value=1)
        query_brotr.delete_service_state = AsyncMock(return_value=1)

        result = await promote_candidates(query_brotr, [candidate])

        query_brotr.insert_relay.assert_awaited_once_with([relay])
        query_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE],
            ["wss://promoted.example.com"],
        )
        assert result == 1

    async def test_empty_candidate_list(self, query_brotr: MagicMock) -> None:
        """Returns 0 immediately for an empty list."""
        query_brotr.insert_relay = AsyncMock()

        result = await promote_candidates(query_brotr, [])

        query_brotr.insert_relay.assert_not_awaited()
        assert result == 0

    async def test_multiple_candidates(self, query_brotr: MagicMock) -> None:
        """Passes all relays to insert_relay and their URLs to delete_service_state."""
        candidates = [
            Candidate(relay=_make_mock_relay("wss://r1.example.com"), failures=0),
            Candidate(relay=_make_mock_relay("wss://r2.example.com"), failures=1),
        ]
        query_brotr.insert_relay = AsyncMock(return_value=2)
        query_brotr.delete_service_state = AsyncMock(return_value=2)

        result = await promote_candidates(query_brotr, candidates)

        query_brotr.insert_relay.assert_awaited_once_with(
            [candidates[0].relay, candidates[1].relay]
        )
        query_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR, ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE, ServiceStateType.CANDIDATE],
            ["wss://r1.example.com", "wss://r2.example.com"],
        )
        assert result == 2


# ============================================================================
# Batch insert helper
# ============================================================================


class TestBatchedInsert:
    """Tests for _batched_insert() helper."""

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        """Returns 0 without calling the method when records is empty."""
        method = AsyncMock(return_value=5)
        result = await _batched_insert(query_brotr, [], method)
        assert result == 0
        method.assert_not_called()

    async def test_under_limit_single_call(self, query_brotr: MagicMock) -> None:
        """Passes all records in one call when under batch limit."""
        query_brotr.config.batch.max_size = 100
        method = AsyncMock(return_value=3)

        result = await _batched_insert(query_brotr, [1, 2, 3], method)

        assert result == 3
        method.assert_awaited_once_with([1, 2, 3])

    async def test_over_limit_splits(self, query_brotr: MagicMock) -> None:
        """Splits records into multiple calls when exceeding batch limit."""
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await _batched_insert(query_brotr, [1, 2, 3, 4, 5], method)

        assert result == 6  # 2 + 2 + 2
        assert method.await_count == 3
        method.assert_any_await([1, 2])
        method.assert_any_await([3, 4])
        method.assert_any_await([5])

    async def test_exact_multiple(self, query_brotr: MagicMock) -> None:
        """Handles exact multiples of batch size correctly."""
        query_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await _batched_insert(query_brotr, [1, 2, 3, 4], method)

        assert result == 4
        assert method.await_count == 2


# ============================================================================
# Batch insert wrappers
# ============================================================================


class TestInsertRelays:
    """Tests for insert_relays() batch splitting."""

    async def test_delegates_to_batched_insert(self, query_brotr: MagicMock) -> None:
        """Calls brotr.insert_relay via _batched_insert."""
        query_brotr.insert_relay = AsyncMock(return_value=2)
        query_brotr.config.batch.max_size = 1

        relays = [Relay("wss://a.example.com"), Relay("wss://b.example.com")]
        result = await insert_relays(query_brotr, relays)

        assert result == 4  # 2 + 2
        assert query_brotr.insert_relay.await_count == 2


class TestInsertEventRelays:
    """Tests for insert_event_relays() batch splitting."""

    async def test_delegates_to_batched_insert(self, query_brotr: MagicMock) -> None:
        """Calls brotr.insert_event_relay via _batched_insert."""
        query_brotr.insert_event_relay = AsyncMock(return_value=3)

        result = await insert_event_relays(query_brotr, [MagicMock(), MagicMock(), MagicMock()])

        assert result == 3
        query_brotr.insert_event_relay.assert_awaited_once()

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        """Returns 0 for empty input."""
        result = await insert_event_relays(query_brotr, [])
        assert result == 0


class TestInsertRelayMetadata:
    """Tests for insert_relay_metadata() batch splitting."""

    async def test_delegates_to_batched_insert(self, query_brotr: MagicMock) -> None:
        """Calls brotr.insert_relay_metadata via _batched_insert."""
        query_brotr.insert_relay_metadata = AsyncMock(return_value=5)

        result = await insert_relay_metadata(query_brotr, [MagicMock(), MagicMock()])

        assert result == 5
        query_brotr.insert_relay_metadata.assert_awaited_once()

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        """Splits records exceeding batch limit."""
        query_brotr.config.batch.max_size = 2
        query_brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_relay_metadata(query_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.insert_relay_metadata.await_count == 3


class TestUpsertServiceStates:
    """Tests for upsert_service_states() batch splitting."""

    async def test_delegates_to_batched_insert(self, query_brotr: MagicMock) -> None:
        """Calls brotr.upsert_service_state via _batched_insert."""
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


# ============================================================================
# Cleanup Stale States Tests
# ============================================================================


class TestCleanupStaleStates:
    """Tests for cleanup_stale()."""

    async def test_candidate_uses_exists(self, query_brotr: MagicMock) -> None:
        """CANDIDATE branch uses EXISTS (relay promoted → candidate is stale)."""
        query_brotr.fetchval = AsyncMock(return_value=0)

        await cleanup_stale(query_brotr, ServiceName.VALIDATOR)

        # Find the CANDIDATE call (first call since CANDIDATE is first in enum)
        calls = query_brotr.fetchval.call_args_list
        candidate_call = next(
            c for c in calls if c[0][1] == ServiceName.VALIDATOR and c[0][2] == ServiceStateType.CANDIDATE
        )
        sql = candidate_call[0][0]
        assert "DELETE FROM service_state" in sql
        assert "AND EXISTS" in sql
        assert "NOT EXISTS" not in sql

    async def test_cursor_uses_not_exists_with_ws_guard(self, query_brotr: MagicMock) -> None:
        """CURSOR branch uses NOT EXISTS with ws% guard."""
        query_brotr.fetchval = AsyncMock(return_value=0)

        await cleanup_stale(query_brotr, ServiceName.FINDER)

        calls = query_brotr.fetchval.call_args_list
        cursor_call = next(
            c for c in calls if c[0][2] == ServiceStateType.CURSOR
        )
        sql = cursor_call[0][0]
        assert "NOT EXISTS" in sql
        assert "LIKE 'ws%'" in sql

    async def test_checkpoint_uses_not_exists_with_ws_guard(self, query_brotr: MagicMock) -> None:
        """CHECKPOINT branch uses NOT EXISTS with ws% guard."""
        query_brotr.fetchval = AsyncMock(return_value=0)

        await cleanup_stale(query_brotr, ServiceName.MONITOR)

        calls = query_brotr.fetchval.call_args_list
        checkpoint_call = next(
            c for c in calls if c[0][2] == ServiceStateType.CHECKPOINT
        )
        sql = checkpoint_call[0][0]
        assert "NOT EXISTS" in sql
        assert "LIKE 'ws%'" in sql

    async def test_aggregates_total(self, query_brotr: MagicMock) -> None:
        """Returns total count across all state types."""
        query_brotr.fetchval = AsyncMock(side_effect=[2, 3, 5])

        result = await cleanup_stale(query_brotr, ServiceName.VALIDATOR)

        assert result == 10

    async def test_returns_zero_for_none(self, query_brotr: MagicMock) -> None:
        """Returns 0 when fetchval returns None for all types."""
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await cleanup_stale(query_brotr, ServiceName.FINDER)

        assert result == 0

    async def test_iterates_all_state_types(self, query_brotr: MagicMock) -> None:
        """Calls fetchval once per ServiceStateType."""
        query_brotr.fetchval = AsyncMock(return_value=0)

        await cleanup_stale(query_brotr, ServiceName.VALIDATOR)

        assert query_brotr.fetchval.call_count == len(ServiceStateType)
