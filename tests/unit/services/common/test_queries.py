"""Unit tests for services.common.queries module.

Tests all 13 domain SQL query functions that centralize database access for
BigBrotr services.  Each function accepts a ``Brotr`` instance and delegates
to one of its query facade methods (fetch, fetchrow, fetchval, execute,
upsert_service_data, transaction).

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

from services.common.constants import DataType, ServiceName
from services.common.queries import (
    count_candidates,
    count_relays_due_for_check,
    delete_exhausted_candidates,
    delete_stale_candidates,
    fetch_candidate_chunk,
    fetch_relays_due_for_check,
    filter_new_relay_urls,
    get_all_relay_urls,
    get_all_relays,
    get_all_service_cursors,
    get_events_with_relay_urls,
    promote_candidates,
    upsert_candidates,
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
    brotr.upsert_service_data = AsyncMock()

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
# TestGetAllRelayUrls
# ============================================================================


class TestGetAllRelayUrls:
    """Tests for get_all_relay_urls()."""

    @pytest.mark.asyncio
    async def test_calls_fetch(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.fetch with a SELECT ... FROM relays query."""
        await get_all_relay_urls(mock_brotr)

        mock_brotr.fetch.assert_awaited_once()
        sql = mock_brotr.fetch.call_args[0][0]
        assert "FROM relays" in sql
        assert "ORDER BY url" in sql

    @pytest.mark.asyncio
    async def test_returns_url_list(self, mock_brotr: MagicMock) -> None:
        """Returns a list of URL strings extracted from rows."""
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"url": "wss://alpha.example.com"}),
                _make_dict_row({"url": "wss://beta.example.com"}),
            ]
        )

        result = await get_all_relay_urls(mock_brotr)

        assert result == ["wss://alpha.example.com", "wss://beta.example.com"]

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no relays exist."""
        mock_brotr.fetch = AsyncMock(return_value=[])

        result = await get_all_relay_urls(mock_brotr)

        assert result == []


# ============================================================================
# TestGetAllRelays
# ============================================================================


class TestGetAllRelays:
    """Tests for get_all_relays()."""

    @pytest.mark.asyncio
    async def test_calls_fetch(self, mock_brotr: MagicMock) -> None:
        """Calls brotr.fetch with a query selecting url, network, discovered_at."""
        await get_all_relays(mock_brotr)

        mock_brotr.fetch.assert_awaited_once()
        sql = mock_brotr.fetch.call_args[0][0]
        assert "url" in sql
        assert "network" in sql
        assert "discovered_at" in sql
        assert "FROM relays" in sql

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, mock_brotr: MagicMock) -> None:
        """Returns a list of dicts created via dict(row)."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await get_all_relays(mock_brotr)

        assert len(result) == 1
        assert result[0]["url"] == "wss://relay.example.com"
        assert result[0]["network"] == "clearnet"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no relays exist."""
        result = await get_all_relays(mock_brotr)

        assert result == []


# ============================================================================
# TestFilterNewRelayUrls
# ============================================================================


class TestFilterNewRelayUrls:
    """Tests for filter_new_relay_urls()."""

    @pytest.mark.asyncio
    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes urls, ServiceName.VALIDATOR, and DataType.CANDIDATE."""
        urls = ["wss://new1.example.com", "wss://new2.example.com"]

        await filter_new_relay_urls(mock_brotr, urls, timeout=10.0)

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "unnest($1::text[])" in sql
        assert "service_name = $2" in sql
        assert "data_type = $3" in sql
        # Positional params
        assert args[0][1] == urls
        assert args[0][2] == ServiceName.VALIDATOR
        assert args[0][3] == DataType.CANDIDATE
        assert args[1]["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_returns_filtered_urls(self, mock_brotr: MagicMock) -> None:
        """Returns only URLs that are genuinely new."""
        mock_brotr.fetch = AsyncMock(
            return_value=[_make_dict_row({"url": "wss://new1.example.com"})]
        )

        result = await filter_new_relay_urls(
            mock_brotr, ["wss://new1.example.com", "wss://existing.example.com"]
        )

        assert result == ["wss://new1.example.com"]

    @pytest.mark.asyncio
    async def test_empty_input(self, mock_brotr: MagicMock) -> None:
        """Works correctly with an empty URL list."""
        result = await filter_new_relay_urls(mock_brotr, [])

        assert result == []


# ============================================================================
# TestCountRelaysDueForCheck
# ============================================================================


class TestCountRelaysDueForCheck:
    """Tests for count_relays_due_for_check()."""

    @pytest.mark.asyncio
    async def test_calls_fetchrow_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes service_name, DataType.CHECKPOINT, networks, and threshold."""
        mock_brotr.fetchrow = AsyncMock(return_value={"count": 42})

        result = await count_relays_due_for_check(
            mock_brotr,
            service_name="monitor",
            threshold=1700000000,
            networks=["clearnet", "tor"],
            timeout=5.0,
        )

        mock_brotr.fetchrow.assert_awaited_once()
        args = mock_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "FROM relays" in sql
        assert "service_name = $1" in sql
        assert "data_type = $2" in sql
        # Positional params
        assert args[0][1] == "monitor"
        assert args[0][2] == DataType.CHECKPOINT
        assert args[0][3] == ["clearnet", "tor"]
        assert args[0][4] == 1700000000
        assert args[1]["timeout"] == 5.0
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_zero_when_row_is_none(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when fetchrow returns None."""
        mock_brotr.fetchrow = AsyncMock(return_value=None)

        result = await count_relays_due_for_check(mock_brotr, "monitor", 1700000000, ["clearnet"])

        assert result == 0


# ============================================================================
# TestFetchRelaysDueForCheck
# ============================================================================


class TestFetchRelaysDueForCheck:
    """Tests for fetch_relays_due_for_check()."""

    @pytest.mark.asyncio
    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes service_name, DataType.CHECKPOINT, networks, threshold, limit."""
        await fetch_relays_due_for_check(
            mock_brotr,
            service_name="monitor",
            threshold=1700000000,
            networks=["clearnet"],
            limit=100,
            timeout=10.0,
        )

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM relays r" in sql
        assert "LEFT JOIN service_data sd" in sql
        assert "LIMIT $5" in sql
        # Positional params
        assert args[0][1] == "monitor"
        assert args[0][2] == DataType.CHECKPOINT
        assert args[0][3] == ["clearnet"]
        assert args[0][4] == 1700000000
        assert args[0][5] == 100
        assert args[1]["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, mock_brotr: MagicMock) -> None:
        """Returns relay dicts with url, network, discovered_at."""
        row = _make_dict_row(
            {"url": "wss://relay.example.com", "network": "clearnet", "discovered_at": 1700000000}
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_relays_due_for_check(
            mock_brotr, "monitor", 1700000000, ["clearnet"], 100
        )

        assert len(result) == 1
        assert result[0]["url"] == "wss://relay.example.com"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no relays are due."""
        result = await fetch_relays_due_for_check(
            mock_brotr, "monitor", 1700000000, ["clearnet"], 100
        )

        assert result == []


# ============================================================================
# TestGetEventsWithRelayUrls
# ============================================================================


class TestGetEventsWithRelayUrls:
    """Tests for get_events_with_relay_urls()."""

    @pytest.mark.asyncio
    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes relay_url, last_seen_at, kinds, and limit."""
        await get_events_with_relay_urls(
            mock_brotr,
            relay_url="wss://source.relay.com",
            last_seen_at=1700000000,
            kinds=[3, 10002],
            limit=500,
        )

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM events e" in sql
        assert "events_relays er" in sql
        assert "relay_url = $1" in sql
        assert "seen_at > $2" in sql
        assert "kind = ANY($3)" in sql
        assert "LIMIT $4" in sql
        # Positional params
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] == 1700000000
        assert args[0][3] == [3, 10002]
        assert args[0][4] == 500

    @pytest.mark.asyncio
    async def test_returns_list_of_event_dicts(self, mock_brotr: MagicMock) -> None:
        """Returns event dicts with id, created_at, kind, tags, content, seen_at."""
        row = _make_dict_row(
            {
                "id": b"\x01" * 32,
                "created_at": 1700000000,
                "kind": 10002,
                "tags": [["r", "wss://relay.example.com"]],
                "content": "",
                "seen_at": 1700000001,
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await get_events_with_relay_urls(
            mock_brotr, "wss://source.relay.com", 0, [10002], 100
        )

        assert len(result) == 1
        assert result[0]["kind"] == 10002
        assert result[0]["seen_at"] == 1700000001

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no matching events exist."""
        result = await get_events_with_relay_urls(mock_brotr, "wss://source.relay.com", 0, [3], 100)

        assert result == []


# ============================================================================
# TestUpsertCandidates
# ============================================================================


class TestUpsertCandidates:
    """Tests for upsert_candidates()."""

    @pytest.mark.asyncio
    async def test_calls_upsert_service_data(self, mock_brotr: MagicMock) -> None:
        """Builds records with ServiceName.VALIDATOR/DataType.CANDIDATE and upserts."""
        relay = _make_mock_relay()

        result = await upsert_candidates(mock_brotr, [relay])

        mock_brotr.upsert_service_data.assert_awaited_once()
        records = mock_brotr.upsert_service_data.call_args[0][0]
        assert len(records) == 1
        service_name, data_type, key, data = records[0]
        assert service_name == ServiceName.VALIDATOR
        assert data_type == DataType.CANDIDATE
        assert key == "wss://relay.example.com"
        assert data["network"] == "clearnet"
        assert data["failed_attempts"] == 0
        assert "inserted_at" in data
        assert result == 1

    @pytest.mark.asyncio
    async def test_multiple_relays(self, mock_brotr: MagicMock) -> None:
        """Handles multiple relays in a single call."""
        relays = [
            _make_mock_relay("wss://r1.example.com"),
            _make_mock_relay("wss://r2.example.com"),
            _make_mock_relay("ws://r3.onion", network_value="tor"),
        ]

        result = await upsert_candidates(mock_brotr, relays)

        records = mock_brotr.upsert_service_data.call_args[0][0]
        assert len(records) == 3
        assert result == 3

    @pytest.mark.asyncio
    async def test_empty_iterable(self, mock_brotr: MagicMock) -> None:
        """Does not call upsert_service_data when given an empty iterable."""
        result = await upsert_candidates(mock_brotr, [])

        mock_brotr.upsert_service_data.assert_not_awaited()
        assert result == 0


# ============================================================================
# TestCountCandidates
# ============================================================================


class TestCountCandidates:
    """Tests for count_candidates()."""

    @pytest.mark.asyncio
    async def test_calls_fetchrow_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, DataType.CANDIDATE, and networks."""
        mock_brotr.fetchrow = AsyncMock(return_value={"count": 15})

        result = await count_candidates(mock_brotr, networks=["clearnet", "tor"], timeout=5.0)

        mock_brotr.fetchrow.assert_awaited_once()
        args = mock_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "FROM service_data" in sql
        assert "service_name = $1" in sql
        assert "data_type = $2" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == DataType.CANDIDATE
        assert args[0][3] == ["clearnet", "tor"]
        assert args[1]["timeout"] == 5.0
        assert result == 15

    @pytest.mark.asyncio
    async def test_returns_zero_when_row_is_none(self, mock_brotr: MagicMock) -> None:
        """Returns 0 when fetchrow returns None."""
        mock_brotr.fetchrow = AsyncMock(return_value=None)

        result = await count_candidates(mock_brotr, ["clearnet"])

        assert result == 0


# ============================================================================
# TestFetchCandidateChunk
# ============================================================================


class TestFetchCandidateChunk:
    """Tests for fetch_candidate_chunk()."""

    @pytest.mark.asyncio
    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, DataType.CANDIDATE, networks, timestamp, limit."""
        await fetch_candidate_chunk(
            mock_brotr,
            networks=["clearnet"],
            before_timestamp=1700000000,
            limit=50,
            timeout=10.0,
        )

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM service_data" in sql
        assert "data_key" in sql
        assert "service_name = $1" in sql
        assert "data_type = $2" in sql
        assert "updated_at < $4" in sql
        assert "LIMIT $5" in sql
        # Positional params
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == DataType.CANDIDATE
        assert args[0][3] == ["clearnet"]
        assert args[0][4] == 1700000000
        assert args[0][5] == 50
        assert args[1]["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self, mock_brotr: MagicMock) -> None:
        """Returns candidate dicts with data_key and data."""
        row = _make_dict_row(
            {
                "data_key": "wss://relay.example.com",
                "data": {"failed_attempts": 0, "network": "clearnet"},
            }
        )
        mock_brotr.fetch = AsyncMock(return_value=[row])

        result = await fetch_candidate_chunk(mock_brotr, ["clearnet"], 1700000000, 50)

        assert len(result) == 1
        assert result[0]["data_key"] == "wss://relay.example.com"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty list when no candidates match."""
        result = await fetch_candidate_chunk(mock_brotr, ["clearnet"], 1700000000, 50)

        assert result == []


# ============================================================================
# TestDeleteStaleCandidates
# ============================================================================


class TestDeleteStaleCandidates:
    """Tests for delete_stale_candidates()."""

    @pytest.mark.asyncio
    async def test_calls_execute_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Calls execute with ServiceName.VALIDATOR and DataType.CANDIDATE."""
        mock_brotr.execute = AsyncMock(return_value="DELETE 5")

        result = await delete_stale_candidates(mock_brotr, timeout=10.0)

        mock_brotr.execute.assert_awaited_once()
        args = mock_brotr.execute.call_args
        sql = args[0][0]
        assert "DELETE FROM service_data" in sql
        assert "service_name = $1" in sql
        assert "data_type = $2" in sql
        assert "data_key IN (SELECT url FROM relays)" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == DataType.CANDIDATE
        assert args[1]["timeout"] == 10.0
        assert result == "DELETE 5"

    @pytest.mark.asyncio
    async def test_returns_command_string(self, mock_brotr: MagicMock) -> None:
        """Returns the PostgreSQL command status string."""
        mock_brotr.execute = AsyncMock(return_value="DELETE 0")

        result = await delete_stale_candidates(mock_brotr)

        assert result == "DELETE 0"


# ============================================================================
# TestDeleteExhaustedCandidates
# ============================================================================


class TestDeleteExhaustedCandidates:
    """Tests for delete_exhausted_candidates()."""

    @pytest.mark.asyncio
    async def test_calls_execute_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes ServiceName.VALIDATOR, DataType.CANDIDATE, and max_failures."""
        mock_brotr.execute = AsyncMock(return_value="DELETE 3")

        result = await delete_exhausted_candidates(mock_brotr, max_failures=5, timeout=10.0)

        mock_brotr.execute.assert_awaited_once()
        args = mock_brotr.execute.call_args
        sql = args[0][0]
        assert "DELETE FROM service_data" in sql
        assert "service_name = $1" in sql
        assert "data_type = $2" in sql
        assert "failed_attempts" in sql
        assert ">= $3" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == DataType.CANDIDATE
        assert args[0][3] == 5
        assert args[1]["timeout"] == 10.0
        assert result == "DELETE 3"

    @pytest.mark.asyncio
    async def test_returns_command_string(self, mock_brotr: MagicMock) -> None:
        """Returns the PostgreSQL command status string."""
        mock_brotr.execute = AsyncMock(return_value="DELETE 0")

        result = await delete_exhausted_candidates(mock_brotr, max_failures=3)

        assert result == "DELETE 0"


# ============================================================================
# TestPromoteCandidates
# ============================================================================


class TestPromoteCandidates:
    """Tests for promote_candidates()."""

    @pytest.mark.asyncio
    async def test_uses_transaction(self, mock_brotr: MagicMock) -> None:
        """Opens a transaction and calls conn.fetchval + conn.execute."""
        relay = _make_mock_relay()
        mock_conn = mock_brotr._mock_conn
        mock_conn.fetchval = AsyncMock(return_value=1)

        result = await promote_candidates(mock_brotr, [relay])

        mock_brotr.transaction.assert_called_once()
        mock_conn.fetchval.assert_awaited_once()
        mock_conn.execute.assert_awaited_once()
        assert result == 1

    @pytest.mark.asyncio
    async def test_inserts_relays_and_deletes_candidates(self, mock_brotr: MagicMock) -> None:
        """Calls relays_insert then deletes matching candidate records."""
        relay = _make_mock_relay("wss://promoted.example.com")
        mock_conn = mock_brotr._mock_conn
        mock_conn.fetchval = AsyncMock(return_value=1)

        await promote_candidates(mock_brotr, [relay])

        # Verify relays_insert call
        fetchval_args = mock_conn.fetchval.call_args
        assert "relays_insert" in fetchval_args[0][0]
        assert fetchval_args[0][1] == ["wss://promoted.example.com"]

        # Verify candidate deletion
        execute_args = mock_conn.execute.call_args
        delete_sql = execute_args[0][0]
        assert "DELETE FROM service_data" in delete_sql
        assert "service_name = $1" in delete_sql
        assert "data_type = $2" in delete_sql
        assert execute_args[0][1] == ServiceName.VALIDATOR
        assert execute_args[0][2] == DataType.CANDIDATE

    @pytest.mark.asyncio
    async def test_empty_relay_list(self, mock_brotr: MagicMock) -> None:
        """Returns 0 immediately for an empty list without opening a transaction."""
        result = await promote_candidates(mock_brotr, [])

        mock_brotr.transaction.assert_not_called()
        assert result == 0

    @pytest.mark.asyncio
    async def test_fetchval_returns_none(self, mock_brotr: MagicMock) -> None:
        """Treats None from fetchval as 0 inserted."""
        relay = _make_mock_relay()
        mock_conn = mock_brotr._mock_conn
        mock_conn.fetchval = AsyncMock(return_value=None)

        result = await promote_candidates(mock_brotr, [relay])

        assert result == 0

    @pytest.mark.asyncio
    async def test_multiple_relays(self, mock_brotr: MagicMock) -> None:
        """Transposes multiple relays into column arrays for relays_insert."""
        relays = [
            _make_mock_relay("wss://r1.example.com", "clearnet", 1700000001),
            _make_mock_relay("wss://r2.example.com", "clearnet", 1700000002),
        ]
        mock_conn = mock_brotr._mock_conn
        mock_conn.fetchval = AsyncMock(return_value=2)

        result = await promote_candidates(mock_brotr, relays)

        fetchval_args = mock_conn.fetchval.call_args
        # Columns: urls, networks, discovered_ats
        assert fetchval_args[0][1] == ["wss://r1.example.com", "wss://r2.example.com"]
        assert fetchval_args[0][2] == ["clearnet", "clearnet"]
        assert fetchval_args[0][3] == [1700000001, 1700000002]
        assert result == 2


# ============================================================================
# TestGetAllServiceCursors
# ============================================================================


class TestGetAllServiceCursors:
    """Tests for get_all_service_cursors()."""

    @pytest.mark.asyncio
    async def test_calls_fetch_with_correct_params(self, mock_brotr: MagicMock) -> None:
        """Passes cursor_field, service_name, and DataType.CURSOR."""
        await get_all_service_cursors(mock_brotr, service_name="finder")

        mock_brotr.fetch.assert_awaited_once()
        args = mock_brotr.fetch.call_args
        sql = args[0][0]
        assert "data_key" in sql
        assert "data->>$1" in sql
        assert "service_name = $2" in sql
        assert "data_type = $3" in sql
        assert args[0][1] == "last_synced_at"
        assert args[0][2] == "finder"
        assert args[0][3] == DataType.CURSOR

    @pytest.mark.asyncio
    async def test_custom_cursor_field(self, mock_brotr: MagicMock) -> None:
        """Uses a custom cursor field name when provided."""
        await get_all_service_cursors(
            mock_brotr, service_name="synchronizer", cursor_field="last_event_at"
        )

        args = mock_brotr.fetch.call_args
        assert args[0][1] == "last_event_at"

    @pytest.mark.asyncio
    async def test_returns_dict_mapping(self, mock_brotr: MagicMock) -> None:
        """Returns a dict mapping data_key to cursor_value."""
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"data_key": "wss://r1.example.com", "cursor_value": 1700000000}),
                _make_dict_row({"data_key": "wss://r2.example.com", "cursor_value": 1700000100}),
            ]
        )

        result = await get_all_service_cursors(mock_brotr, "finder")

        assert result == {
            "wss://r1.example.com": 1700000000,
            "wss://r2.example.com": 1700000100,
        }

    @pytest.mark.asyncio
    async def test_filters_none_cursor_values(self, mock_brotr: MagicMock) -> None:
        """Skips rows where cursor_value is None."""
        mock_brotr.fetch = AsyncMock(
            return_value=[
                _make_dict_row({"data_key": "wss://r1.example.com", "cursor_value": 1700000000}),
                _make_dict_row({"data_key": "wss://r2.example.com", "cursor_value": None}),
            ]
        )

        result = await get_all_service_cursors(mock_brotr, "finder")

        assert result == {"wss://r1.example.com": 1700000000}
        assert "wss://r2.example.com" not in result

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_brotr: MagicMock) -> None:
        """Returns an empty dict when no cursors exist."""
        result = await get_all_service_cursors(mock_brotr, "finder")

        assert result == {}
