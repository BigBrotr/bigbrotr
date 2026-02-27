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
    cleanup_service_state,
    count_candidates,
    delete_exhausted_candidates,
    fetch_all_relays,
    fetch_candidates,
    fetch_relays_to_monitor,
    filter_new_relays,
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
def mock_brotr() -> MagicMock:
    """Create a mock Brotr with all query facade methods stubbed."""
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchrow = AsyncMock(return_value={"count": 0})
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.execute = AsyncMock(return_value="DELETE 0")
    brotr.upsert_service_state = AsyncMock()
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
    """Tests for fetch_all_relays()."""

    async def test_calls_fetch(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.fetch with a query selecting url, network, discovered_at."""
        await fetch_all_relays(mock_brotr)

        mock_brotr.fetch.assert_awaited_once()
        sql = mock_brotr.fetch.call_args[0][0]
        assert "url" in sql
        assert "network" in sql
        assert "discovered_at" in sql
        assert "FROM relay" in sql

    async def test_returns_relay_objects(self, mock_brotr: MagicMock) -> None:
        """Returns a list of Relay domain objects."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_all_relays(mock_brotr)

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"
        assert result[0].network.value == "clearnet"

    async def test_skips_invalid_urls(self, mock_brotr: MagicMock) -> None:
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
        mock_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_all_relays(mock_brotr)

        assert len(result) == 2
        assert result[0].url == "wss://valid.relay.com"
        assert result[1].url == "wss://also.valid.com"

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no relays exist."""
        result = await fetch_all_relays(mock_brotr)

        assert result == []


# ============================================================================
# TestFilterNewRelayUrls
# ============================================================================


class TestFilterNewRelays:
    """Tests for filter_new_relays()."""

    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes urls, ServiceName.VALIDATOR, and ServiceStateType.CANDIDATE."""
        relays = [Relay("wss://new1.example.com"), Relay("wss://new2.example.com")]

        await filter_new_relays(mock_brotr, relays)

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "unnest($1::text[])" in sql
        assert "service_name = $2" in sql
        assert "state_type = $3" in sql
        assert args[0][1] == ["wss://new1.example.com", "wss://new2.example.com"]
        assert args[0][2] == ServiceName.VALIDATOR
        assert args[0][3] == ServiceStateType.CANDIDATE

    async def test_returns_filtered_relays(self, mock_brotr: MagicMock) -> None:
        """Returns only relays whose URL is genuinely new."""
        mock_brotr.fetch = AsyncMock(
            return_value=[_make_dict_row({"url": "wss://new1.example.com"})]
        )
        relays = [Relay("wss://new1.example.com"), Relay("wss://existing.example.com")]

        result = await filter_new_relays(mock_brotr, relays)

        assert len(result) == 1
        assert result[0].url == "wss://new1.example.com"

    async def test_empty_input(self, mock_brotr: MagicMock) -> None:
        """Returns empty list without querying the database."""
        result = await filter_new_relays(mock_brotr, [])

        assert result == []
        mock_brotr.fetch.assert_not_awaited()


# ============================================================================
# TestFetchRelaysToMonitor
# ============================================================================


class TestFetchRelaysToMonitor:
    """Tests for fetch_relays_to_monitor()."""

    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes networks, monitored_before, ServiceName.MONITOR, ServiceStateType.MONITORING."""
        await fetch_relays_to_monitor(
            mock_brotr,
            monitored_before=1700000000,
            networks=[NetworkType.CLEARNET],
        )

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM relay r" in sql
        assert "LEFT JOIN service_state ss" in sql
        assert "service_name = $3" in sql
        assert "state_type = $4" in sql
        assert args[0][1] == [NetworkType.CLEARNET]
        assert args[0][2] == 1700000000
        assert args[0][3] == ServiceName.MONITOR
        assert args[0][4] == ServiceStateType.MONITORING

    async def test_returns_relay_objects(self, mock_brotr: MagicMock) -> None:
        """Returns Relay domain objects."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_to_monitor(mock_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://relay.example.com"
        assert result[0].network.value == "clearnet"

    async def test_skips_invalid_urls(self, mock_brotr: MagicMock) -> None:
        """Skips rows with invalid URLs instead of raising."""
        rows = [
            _make_dict_row(
                {"url": "wss://valid.relay.com", "network": "clearnet", "discovered_at": 1700000000}
            ),
            _make_dict_row(
                {"url": "not-valid", "network": "clearnet", "discovered_at": 1700000000}
            ),
        ]
        mock_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_relays_to_monitor(mock_brotr, 1700000000, [NetworkType.CLEARNET])

        assert len(result) == 1
        assert result[0].url == "wss://valid.relay.com"

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no relays are due."""
        result = await fetch_relays_to_monitor(mock_brotr, 1700000000, [NetworkType.CLEARNET])

        assert result == []


# ============================================================================
# TestFetchEventTagvalues
# ============================================================================


class TestScanEventRelay:
    """Tests for scan_event_relay()."""

    async def test_scan_with_cursor(self, mock_brotr: MagicMock) -> None:
        """Passes cursor fields and limit to the SQL query."""
        event_id = b"\xab" * 32
        cursor = EventRelayCursor(
            relay_url="wss://source.relay.com",
            seen_at=1700000000,
            event_id=event_id,
        )
        await scan_event_relay(mock_brotr, cursor, limit=500)

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
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

    async def test_scan_no_cursor(self, mock_brotr: MagicMock) -> None:
        """Passes None for cursor fields when starting fresh."""
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        await scan_event_relay(mock_brotr, cursor, limit=100)

        args = mock_brotr.fetch.call_args
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] is None
        assert args[0][3] is None

    async def test_scan_returns_dicts(self, mock_brotr: MagicMock) -> None:
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
                "tagvalues": ["wss://relay.example.com", "a" * 64],
                "seen_at": 1700000001,
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")

        result = await scan_event_relay(mock_brotr, cursor, limit=100)

        assert len(result) == 1
        assert result[0]["tagvalues"] == ["wss://relay.example.com", "a" * 64]
        assert result[0]["seen_at"] == 1700000001
        assert result[0]["event_id"] == event_id

    async def test_scan_empty(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        cursor = EventRelayCursor(relay_url="wss://source.relay.com")
        result = await scan_event_relay(mock_brotr, cursor, limit=100)

        assert result == []


class TestScanEvent:
    """Tests for scan_event()."""

    async def test_scan_with_cursor(self, mock_brotr: MagicMock) -> None:
        """Passes cursor fields and limit to the SQL query."""
        event_id = b"\xab" * 32
        cursor = EventCursor(created_at=1700000000, event_id=event_id)
        await scan_event(mock_brotr, cursor, limit=500)

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM event" in sql
        assert "IS NULL OR (created_at, id) >" in sql
        assert "id ASC" in sql
        assert "LIMIT $3" in sql
        assert args[0][1] == 1700000000
        assert args[0][2] == event_id
        assert args[0][3] == 500

    async def test_scan_no_cursor(self, mock_brotr: MagicMock) -> None:
        """Passes None for cursor fields when starting fresh."""
        cursor = EventCursor()
        await scan_event(mock_brotr, cursor, limit=100)

        args = mock_brotr.fetch.call_args
        assert args[0][1] is None
        assert args[0][2] is None

    async def test_scan_empty(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        cursor = EventCursor()
        result = await scan_event(mock_brotr, cursor, limit=100)

        assert result == []


# ============================================================================
# TestInsertCandidates
# ============================================================================


class TestInsertCandidates:
    """Tests for insert_relays_as_candidates()."""

    async def test_filters_then_upserts(self, mock_brotr: MagicMock) -> None:
        """Calls filter_new_relays internally, then upserts only new relays."""
        relay = _make_mock_relay()
        mock_brotr.fetch = AsyncMock(
            return_value=[_make_dict_row({"url": "wss://relay.example.com"})]
        )

        result = await insert_relays_as_candidates(mock_brotr, [relay])

        # filter_new_relays called via brotr.fetch
        mock_brotr.fetch.assert_awaited_once()
        sql = mock_brotr.fetch.call_args[0][0]
        assert "unnest($1::text[])" in sql

        # upsert_service_state called with the filtered relay
        mock_brotr.upsert_service_state.assert_awaited_once()
        records = mock_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        record = records[0]
        assert record.service_name == ServiceName.VALIDATOR
        assert record.state_type == ServiceStateType.CANDIDATE
        assert record.state_key == "wss://relay.example.com"
        assert record.state_value["network"] == "clearnet"
        assert record.state_value["failures"] == 0
        assert "inserted_at" in record.state_value
        assert result == 1

    async def test_multiple_relays_partially_new(self, mock_brotr: MagicMock) -> None:
        """Only inserts relays that pass the filter."""
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
            _make_mock_relay("ws://r3.onion", network_value="tor"),
        ]
        # Only r1 and r3 are new
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"url": "wss://r1.example.com"}),
                _make_dict_row({"url": "ws://r3.onion"}),
            ]
        )

        result = await insert_relays_as_candidates(mock_brotr, relays)

        records = mock_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        assert result == 2
        keys = {r.state_key for r in records}
        assert keys == {"wss://r1.example.com", "ws://r3.onion"}

    async def test_all_filtered_out(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when all relays already exist (filter returns empty)."""
        relay = _make_mock_relay()
        mock_brotr.fetch = AsyncMock(return_value=[])

        result = await insert_relays_as_candidates(mock_brotr, [relay])

        mock_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_iterable(self, mock_brotr: MagicMock) -> None:
        """Does not call fetch or upsert_service_state when given an empty iterable."""
        result = await insert_relays_as_candidates(mock_brotr, [])

        mock_brotr.fetch.assert_not_awaited()
        mock_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_batching_large_input(self, mock_brotr: MagicMock) -> None:
        """Splits into batches when relays exceed batch.max_size."""
        mock_brotr.config.batch.max_size = 2
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
            _make_mock_relay("wss://r3.example.com"),
        ]
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"url": "wss://r1.example.com"}),
                _make_dict_row({"url": "wss://r2.example.com"}),
                _make_dict_row({"url": "wss://r3.example.com"}),
            ]
        )

        result = await insert_relays_as_candidates(mock_brotr, relays)

        assert mock_brotr.upsert_service_state.await_count == 2  # 2 + 1
        assert result == 3


# ============================================================================
# TestCountCandidates
# ============================================================================


class TestCountCandidates:
    """Tests for count_candidates()."""

    async def test_calls_fetchrow_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, and networks."""
        mock_brotr.fetchrow = AsyncMock(return_value={"count": 15})

        result = await count_candidates(
            mock_brotr, networks=[NetworkType.CLEARNET, NetworkType.TOR]
        )

        mock_brotr.fetchrow.assert_awaited_once()
        args = mock_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert args[0][3] == [NetworkType.CLEARNET, NetworkType.TOR]
        assert result == 15

    async def test_returns_zero_when_row_is_none(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when fetchrow returns None."""
        mock_brotr.fetchrow = AsyncMock(return_value=None)

        result = await count_candidates(mock_brotr, [NetworkType.CLEARNET])

        assert result == 0


# ============================================================================
# TestFetchCandidates
# ============================================================================


class TestFetchCandidates:
    """Tests for fetch_candidates()."""

    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, networks, timestamp, limit."""
        await fetch_candidates(
            mock_brotr,
            networks=[NetworkType.CLEARNET],
            updated_before=1700000000,
            limit=50,
        )

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
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

    async def test_returns_candidate_objects(self, mock_brotr: MagicMock) -> None:
        """Returns Candidate domain objects constructed from rows."""
        row = _make_dict_row(
            {
                "state_key": "wss://relay.example.com",
                "state_value": {"failures": 0, "network": "clearnet"},
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert str(result[0].relay.url) == "wss://relay.example.com"
        assert result[0].failures == 0

    async def test_skips_invalid_urls(self, mock_brotr: MagicMock) -> None:
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
        mock_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert str(result[0].relay.url) == "wss://relay.example.com"

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no candidates match."""
        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert result == []


# ============================================================================
# TestDeleteExhaustedCandidates
# ============================================================================


class TestDeleteExhaustedCandidates:
    """Tests for delete_exhausted_candidates()."""

    async def test_calls_fetchval_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, ServiceStateType.CANDIDATE, and max_failures."""
        mock_brotr.fetchval = AsyncMock(return_value=3)

        result = await delete_exhausted_candidates(mock_brotr, max_failures=5)

        mock_brotr.fetchval.assert_awaited_once()
        args = mock_brotr.fetchval.call_args
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

    async def test_returns_zero_when_none_deleted(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when no rows are deleted."""
        mock_brotr.fetchval = AsyncMock(return_value=0)

        result = await delete_exhausted_candidates(mock_brotr, max_failures=3)

        assert result == 0


# ============================================================================
# TestPromoteCandidates
# ============================================================================


class TestPromoteCandidates:
    """Tests for promote_candidates()."""

    async def test_inserts_relays_and_deletes_candidates(self, mock_brotr: MagicMock) -> None:
        """Calls insert_relay then delete_service_state."""
        relay = _make_mock_relay("wss://promoted.example.com")
        candidate = Candidate(relay=relay, data={"failures": 0})
        mock_brotr.insert_relay = AsyncMock(return_value=1)
        mock_brotr.delete_service_state = AsyncMock(return_value=1)

        result = await promote_candidates(mock_brotr, [candidate])

        mock_brotr.insert_relay.assert_awaited_once_with([relay])
        mock_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE],
            ["wss://promoted.example.com"],
        )
        assert result == 1

    async def test_empty_candidate_list(self, mock_brotr: MagicMock) -> None:
        """Returns 0 immediately for an empty list."""
        mock_brotr.insert_relay = AsyncMock()

        result = await promote_candidates(mock_brotr, [])

        mock_brotr.insert_relay.assert_not_awaited()
        assert result == 0

    async def test_multiple_candidates(self, mock_brotr: MagicMock) -> None:
        """Passes all relays to insert_relay and their URLs to delete_service_state."""
        candidates = [
            Candidate(relay=_make_mock_relay("wss://r1.example.com"), data={"failures": 0}),
            Candidate(relay=_make_mock_relay("wss://r2.example.com"), data={"failures": 1}),
        ]
        mock_brotr.insert_relay = AsyncMock(return_value=2)
        mock_brotr.delete_service_state = AsyncMock(return_value=2)

        result = await promote_candidates(mock_brotr, candidates)

        mock_brotr.insert_relay.assert_awaited_once_with([candidates[0].relay, candidates[1].relay])
        mock_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR, ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE, ServiceStateType.CANDIDATE],
            ["wss://r1.example.com", "wss://r2.example.com"],
        )
        assert result == 2


# ============================================================================
# TestDeleteStaleState
# ============================================================================


class TestCleanupStaleState:
    """Tests for cleanup_service_state()."""

    async def test_cursor_uses_not_exists(self, mock_brotr: MagicMock) -> None:
        """CURSOR state uses NOT EXISTS (relay removed → state is stale)."""
        mock_brotr.fetchval = AsyncMock(return_value=3)

        result = await cleanup_service_state(
            mock_brotr, ServiceName.FINDER, ServiceStateType.CURSOR
        )

        mock_brotr.fetchval.assert_awaited_once()
        args = mock_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.FINDER
        assert args[0][2] == ServiceStateType.CURSOR
        assert result == 3

    async def test_monitoring_uses_not_exists(self, mock_brotr: MagicMock) -> None:
        """MONITORING state uses NOT EXISTS (relay removed → state is stale)."""
        mock_brotr.fetchval = AsyncMock(return_value=5)

        result = await cleanup_service_state(
            mock_brotr, ServiceName.MONITOR, ServiceStateType.MONITORING
        )

        args = mock_brotr.fetchval.call_args
        sql = args[0][0]
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.MONITOR
        assert args[0][2] == ServiceStateType.MONITORING
        assert result == 5

    async def test_candidate_uses_exists(self, mock_brotr: MagicMock) -> None:
        """CANDIDATE state uses EXISTS (relay promoted → candidate is stale)."""
        mock_brotr.fetchval = AsyncMock(return_value=7)

        result = await cleanup_service_state(
            mock_brotr, ServiceName.VALIDATOR, ServiceStateType.CANDIDATE
        )

        args = mock_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "AND EXISTS" in sql
        assert "NOT EXISTS" not in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert result == 7

    async def test_returns_zero_when_none_deleted(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when no stale rows exist."""
        mock_brotr.fetchval = AsyncMock(return_value=0)

        result = await cleanup_service_state(
            mock_brotr, ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR
        )

        assert result == 0

    async def test_rejects_non_relay_keyed_type(self, mock_brotr: MagicMock) -> None:
        """Raises ValueError for state types whose keys are not relay URLs."""
        with pytest.raises(ValueError, match="relay-keyed"):
            await cleanup_service_state(
                mock_brotr, ServiceName.MONITOR, ServiceStateType.PUBLICATION
            )


# ============================================================================
# Batch insert helper
# ============================================================================


class TestBatchedInsert:
    """Tests for _batched_insert() helper."""

    async def test_empty_returns_zero(self, mock_brotr: MagicMock) -> None:
        """Returns 0 without calling the method when records is empty."""
        method = AsyncMock(return_value=5)
        result = await _batched_insert(mock_brotr, [], method)
        assert result == 0
        method.assert_not_called()

    async def test_under_limit_single_call(self, mock_brotr: MagicMock) -> None:
        """Passes all records in one call when under batch limit."""
        mock_brotr.config.batch.max_size = 100
        method = AsyncMock(return_value=3)

        result = await _batched_insert(mock_brotr, [1, 2, 3], method)

        assert result == 3
        method.assert_awaited_once_with([1, 2, 3])

    async def test_over_limit_splits(self, mock_brotr: MagicMock) -> None:
        """Splits records into multiple calls when exceeding batch limit."""
        mock_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await _batched_insert(mock_brotr, [1, 2, 3, 4, 5], method)

        assert result == 6  # 2 + 2 + 2
        assert method.await_count == 3
        method.assert_any_await([1, 2])
        method.assert_any_await([3, 4])
        method.assert_any_await([5])

    async def test_exact_multiple(self, mock_brotr: MagicMock) -> None:
        """Handles exact multiples of batch size correctly."""
        mock_brotr.config.batch.max_size = 2
        method = AsyncMock(return_value=2)

        result = await _batched_insert(mock_brotr, [1, 2, 3, 4], method)

        assert result == 4
        assert method.await_count == 2


# ============================================================================
# Batch insert wrappers
# ============================================================================


class TestInsertRelays:
    """Tests for insert_relays() batch splitting."""

    async def test_delegates_to_batched_insert(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.insert_relay via _batched_insert."""
        mock_brotr.insert_relay = AsyncMock(return_value=2)
        mock_brotr.config.batch.max_size = 1

        relays = [Relay("wss://a.example.com"), Relay("wss://b.example.com")]
        result = await insert_relays(mock_brotr, relays)

        assert result == 4  # 2 + 2
        assert mock_brotr.insert_relay.await_count == 2


class TestInsertEventRelays:
    """Tests for insert_event_relays() batch splitting."""

    async def test_delegates_to_batched_insert(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.insert_event_relay via _batched_insert."""
        mock_brotr.insert_event_relay = AsyncMock(return_value=3)

        result = await insert_event_relays(mock_brotr, [MagicMock(), MagicMock(), MagicMock()])

        assert result == 3
        mock_brotr.insert_event_relay.assert_awaited_once()

    async def test_empty_returns_zero(self, mock_brotr: MagicMock) -> None:
        """Returns 0 for empty input."""
        result = await insert_event_relays(mock_brotr, [])
        assert result == 0


class TestInsertRelayMetadata:
    """Tests for insert_relay_metadata() batch splitting."""

    async def test_delegates_to_batched_insert(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.insert_relay_metadata via _batched_insert."""
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=5)

        result = await insert_relay_metadata(mock_brotr, [MagicMock(), MagicMock()])

        assert result == 5
        mock_brotr.insert_relay_metadata.assert_awaited_once()

    async def test_splits_large_batch(self, mock_brotr: MagicMock) -> None:
        """Splits records exceeding batch limit."""
        mock_brotr.config.batch.max_size = 2
        mock_brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_relay_metadata(mock_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert mock_brotr.insert_relay_metadata.await_count == 3


class TestUpsertServiceStates:
    """Tests for upsert_service_states() batch splitting."""

    async def test_delegates_to_batched_insert(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.upsert_service_state via _batched_insert."""
        mock_brotr.upsert_service_state = AsyncMock(return_value=2)

        records = [MagicMock(), MagicMock()]
        result = await upsert_service_states(mock_brotr, records)

        assert result == 2
        mock_brotr.upsert_service_state.assert_awaited_once()

    async def test_splits_large_batch(self, mock_brotr: MagicMock) -> None:
        """Splits records exceeding batch limit."""
        mock_brotr.config.batch.max_size = 2
        mock_brotr.upsert_service_state = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await upsert_service_states(mock_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert mock_brotr.upsert_service_state.await_count == 3
