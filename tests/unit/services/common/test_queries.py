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
    count_candidates,
    delete_exhausted_candidates,
    delete_orphan_cursors,
    delete_stale_candidates,
    fetch_all_relays,
    fetch_candidates,
    fetch_event_tagvalues,
    fetch_relays_to_monitor,
    filter_new_relays,
    get_all_cursor_values,
    insert_candidates,
    promote_candidates,
)


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
        """Returns a list of Relay domain objects constructed via from_db_params."""
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
        """Returns Relay domain objects constructed via from_db_params."""
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


class TestFetchEventTagvalues:
    """Tests for fetch_event_tagvalues()."""

    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes relay_url, cursor_seen_at, cursor_event_id, and limit."""
        event_id = b"\xab" * 32
        await fetch_event_tagvalues(
            mock_brotr,
            relay_url="wss://source.relay.com",
            cursor_seen_at=1700000000,
            cursor_event_id=event_id,
            limit=500,
        )

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

    async def test_null_cursor_passes_none(self, mock_brotr: MagicMock) -> None:
        """Passes None for both cursor components when starting fresh."""
        await fetch_event_tagvalues(
            mock_brotr,
            relay_url="wss://source.relay.com",
            cursor_seen_at=None,
            cursor_event_id=None,
            limit=100,
        )

        args = mock_brotr.fetch.call_args
        assert args[0][2] is None
        assert args[0][3] is None

    async def test_returns_list_of_event_dicts(self, mock_brotr: MagicMock) -> None:
        """Returns event dicts with tagvalues, seen_at, and event_id."""
        event_id = b"\xab" * 32
        row = _make_dict_row(
            {
                "tagvalues": ["wss://relay.example.com", "a" * 64],
                "seen_at": 1700000001,
                "event_id": event_id,
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_event_tagvalues(mock_brotr, "wss://source.relay.com", None, None, 100)

        assert len(result) == 1
        assert result[0]["tagvalues"] == ["wss://relay.example.com", "a" * 64]
        assert result[0]["seen_at"] == 1700000001
        assert result[0]["event_id"] == event_id

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        result = await fetch_event_tagvalues(mock_brotr, "wss://source.relay.com", None, None, 100)

        assert result == []


# ============================================================================
# TestInsertCandidates
# ============================================================================


class TestInsertCandidates:
    """Tests for insert_candidates()."""

    async def test_filters_then_upserts(self, mock_brotr: MagicMock) -> None:
        """Calls filter_new_relays internally, then upserts only new relays."""
        relay = _make_mock_relay()
        mock_brotr.fetch = AsyncMock(
            return_value=[_make_dict_row({"url": "wss://relay.example.com"})]
        )

        result = await insert_candidates(mock_brotr, [relay])

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

        result = await insert_candidates(mock_brotr, relays)

        records = mock_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        assert result == 2
        keys = {r.state_key for r in records}
        assert keys == {"wss://r1.example.com", "ws://r3.onion"}

    async def test_all_filtered_out(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when all relays already exist (filter returns empty)."""
        relay = _make_mock_relay()
        mock_brotr.fetch = AsyncMock(return_value=[])

        result = await insert_candidates(mock_brotr, [relay])

        mock_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_iterable(self, mock_brotr: MagicMock) -> None:
        """Does not call fetch or upsert_service_state when given an empty iterable."""
        result = await insert_candidates(mock_brotr, [])

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

        result = await insert_candidates(mock_brotr, relays)

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
        assert "service_name, state_type, state_key, state_value, updated_at" in sql
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

    async def test_returns_service_state_objects(self, mock_brotr: MagicMock) -> None:
        """Returns ServiceState domain objects constructed from rows."""
        row = _make_dict_row(
            {
                "service_name": "validator",
                "state_type": "candidate",
                "state_key": "wss://relay.example.com",
                "state_value": {"failures": 0, "network": "clearnet"},
                "updated_at": 1700000000,
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert result[0].state_key == "wss://relay.example.com"
        assert result[0].service_name == ServiceName.VALIDATOR
        assert result[0].state_type == ServiceStateType.CANDIDATE

    async def test_skips_invalid_rows(self, mock_brotr: MagicMock) -> None:
        """Skips rows that fail ServiceState construction."""
        rows = [
            _make_dict_row(
                {
                    "service_name": "validator",
                    "state_type": "candidate",
                    "state_key": "wss://relay.example.com",
                    "state_value": {"failures": 0, "network": "clearnet"},
                    "updated_at": 1700000000,
                }
            ),
            _make_dict_row(
                {
                    "service_name": "validator",
                    "state_type": "candidate",
                    "state_key": "",
                    "state_value": {"failures": 0, "network": "clearnet"},
                    "updated_at": 1700000000,
                }
            ),
        ]
        mock_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert result[0].state_key == "wss://relay.example.com"

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no candidates match."""
        result = await fetch_candidates(mock_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert result == []


# ============================================================================
# TestDeleteStaleCandidates
# ============================================================================


class TestDeleteStaleCandidates:
    """Tests for delete_stale_candidates()."""

    async def test_calls_fetchval_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Calls fetchval with ServiceName.VALIDATOR and ServiceStateType.CANDIDATE."""
        mock_brotr.fetchval = AsyncMock(return_value=5)

        result = await delete_stale_candidates(mock_brotr)

        mock_brotr.fetchval.assert_awaited_once()
        args = mock_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CANDIDATE
        assert result == 5

    async def test_returns_zero_when_none_deleted(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when no rows are deleted."""
        mock_brotr.fetchval = AsyncMock(return_value=0)

        result = await delete_stale_candidates(mock_brotr)

        assert result == 0


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
        mock_brotr.insert_relay = AsyncMock(return_value=1)
        mock_brotr.delete_service_state = AsyncMock(return_value=1)

        result = await promote_candidates(mock_brotr, [relay])

        mock_brotr.insert_relay.assert_awaited_once_with([relay])
        mock_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE],
            ["wss://promoted.example.com"],
        )
        assert result == 1

    async def test_empty_relay_list(self, mock_brotr: MagicMock) -> None:
        """Returns 0 immediately for an empty list."""
        mock_brotr.insert_relay = AsyncMock()

        result = await promote_candidates(mock_brotr, [])

        mock_brotr.insert_relay.assert_not_awaited()
        assert result == 0

    async def test_multiple_relays(self, mock_brotr: MagicMock) -> None:
        """Passes all relays to insert_relay and their URLs to delete_service_state."""
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
        ]
        mock_brotr.insert_relay = AsyncMock(return_value=2)
        mock_brotr.delete_service_state = AsyncMock(return_value=2)

        result = await promote_candidates(mock_brotr, relays)

        mock_brotr.insert_relay.assert_awaited_once_with(relays)
        mock_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR, ServiceName.VALIDATOR],
            [ServiceStateType.CANDIDATE, ServiceStateType.CANDIDATE],
            ["wss://r1.example.com", "wss://r2.example.com"],
        )
        assert result == 2


# ============================================================================
# TestGetAllCursorValues
# ============================================================================


class TestGetAllCursorValues:
    """Tests for get_all_cursor_values()."""

    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes service_name and ServiceStateType.CURSOR."""
        await get_all_cursor_values(mock_brotr, service_name=ServiceName.FINDER)

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "state_key" in sql
        assert "state_value" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert args[0][1] == ServiceName.FINDER
        assert args[0][2] == ServiceStateType.CURSOR

    async def test_returns_dict_mapping(self, mock_brotr: MagicMock) -> None:
        """Returns a dict mapping state_key to state_value dict."""
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row(
                    {
                        "state_key": "wss://r1.example.com",
                        "state_value": {"seen_at": 1700000000, "event_id": "ab" * 32},
                    }
                ),
                _make_dict_row(
                    {
                        "state_key": "wss://r2.example.com",
                        "state_value": {"last_synced_at": 1700000100},
                    }
                ),
            ]
        )

        result = await get_all_cursor_values(mock_brotr, ServiceName.FINDER)

        assert result == {
            "wss://r1.example.com": {"seen_at": 1700000000, "event_id": "ab" * 32},
            "wss://r2.example.com": {"last_synced_at": 1700000100},
        }

    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty dict when no cursors exist."""
        result = await get_all_cursor_values(mock_brotr, ServiceName.FINDER)

        assert result == {}


# ============================================================================
# TestDeleteOrphanCursors
# ============================================================================


class TestDeleteOrphanCursors:
    """Tests for delete_orphan_cursors()."""

    async def test_calls_fetchval_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes service_name and ServiceStateType.CURSOR."""
        mock_brotr.fetchval = AsyncMock(return_value=3)

        result = await delete_orphan_cursors(mock_brotr, service_name=ServiceName.FINDER)

        mock_brotr.fetchval.assert_awaited_once()
        args = mock_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.FINDER
        assert args[0][2] == ServiceStateType.CURSOR
        assert result == 3

    async def test_returns_zero_when_none_deleted(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when no orphan cursors exist."""
        mock_brotr.fetchval = AsyncMock(return_value=0)

        result = await delete_orphan_cursors(mock_brotr, ServiceName.SYNCHRONIZER)

        assert result == 0

    async def test_works_for_synchronizer(self, mock_brotr: MagicMock) -> None:
        """Works correctly with ServiceName.SYNCHRONIZER."""
        mock_brotr.fetchval = AsyncMock(return_value=7)

        result = await delete_orphan_cursors(mock_brotr, ServiceName.SYNCHRONIZER)

        args = mock_brotr.fetchval.call_args
        assert args[0][1] == ServiceName.SYNCHRONIZER
        assert result == 7
