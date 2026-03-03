"""Unit tests for the finder service package."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.types import ApiCheckpoint, EventRelayCursor
from bigbrotr.services.common.utils import parse_relay
from bigbrotr.services.finder import (
    ApiConfig,
    ApiSourceConfig,
    EventsConfig,
    Finder,
    FinderConfig,
)
from bigbrotr.services.finder.queries import (
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_event_relay_cursors,
    load_api_checkpoints,
    save_api_checkpoints,
    save_event_relay_cursor,
    scan_event_relay,
)
from bigbrotr.services.finder.utils import (
    extract_relays_from_response,
    extract_relays_from_tagvalues,
)


# ============================================================================
# Fixtures & Helpers
# ============================================================================


def _mock_api_response(data: Any) -> MagicMock:
    body = json.dumps(data).encode()
    content = MagicMock()
    content.read = AsyncMock(side_effect=[body, b""])

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


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
# Configs
# ============================================================================


class TestEventsConfig:
    def test_default_values(self) -> None:
        config = EventsConfig()
        assert config.enabled is True
        assert config.batch_size == 100
        assert config.parallel_relays == 50
        assert config.max_relay_time is None
        assert config.max_duration == 86400.0

    def test_disabled(self) -> None:
        config = EventsConfig(enabled=False)
        assert config.enabled is False

    def test_batch_size_bounds(self) -> None:
        config_min = EventsConfig(batch_size=100)
        assert config_min.batch_size == 100

        config_max = EventsConfig(batch_size=1000)
        assert config_max.batch_size == 1000

        with pytest.raises(ValueError):
            EventsConfig(batch_size=5)

        with pytest.raises(ValueError):
            EventsConfig(batch_size=1001)

    def test_parallel_relays_bounds(self) -> None:
        config_min = EventsConfig(parallel_relays=1)
        assert config_min.parallel_relays == 1

        config_max = EventsConfig(parallel_relays=200)
        assert config_max.parallel_relays == 200

        with pytest.raises(ValueError):
            EventsConfig(parallel_relays=0)

        with pytest.raises(ValueError):
            EventsConfig(parallel_relays=201)

    def test_max_relay_time_custom(self) -> None:
        config = EventsConfig(max_relay_time=30.0)
        assert config.max_relay_time == 30.0

    def test_max_relay_time_below_minimum(self) -> None:
        with pytest.raises(ValueError):
            EventsConfig(max_relay_time=0.5)

    def test_max_duration_custom(self) -> None:
        config = EventsConfig(max_duration=120.0)
        assert config.max_duration == 120.0

    def test_max_duration_below_minimum(self) -> None:
        with pytest.raises(ValueError):
            EventsConfig(max_duration=0.5)

    def test_max_relay_time_above_upper_bound(self) -> None:
        with pytest.raises(ValueError):
            EventsConfig(max_relay_time=86_401.0)

    def test_max_duration_above_upper_bound(self) -> None:
        with pytest.raises(ValueError):
            EventsConfig(max_duration=604_801.0)


class TestApiSourceConfig:
    def test_default_values(self) -> None:
        config = ApiSourceConfig(url="https://api.example.com")

        assert config.url == "https://api.example.com"
        assert config.enabled is True
        assert config.timeout == 30.0
        assert config.expression == "[*]"

    def test_custom_values(self) -> None:
        config = ApiSourceConfig(
            url="https://custom.api.com",
            enabled=False,
            timeout=60.0,
        )

        assert config.url == "https://custom.api.com"
        assert config.enabled is False
        assert config.timeout == 60.0

    def test_timeout_bounds(self) -> None:
        # Min bound (connect_timeout must not exceed timeout)
        config_min = ApiSourceConfig(url="https://api.com", timeout=0.1, connect_timeout=0.1)
        assert config_min.timeout == 0.1

        # Max bound
        config_max = ApiSourceConfig(url="https://api.com", timeout=120.0)
        assert config_max.timeout == 120.0

    def test_custom_expression(self) -> None:
        config = ApiSourceConfig(
            url="https://api.example.com",
            expression="data.relays[*].url",
        )
        assert config.expression == "data.relays[*].url"

    def test_invalid_expression_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid JMESPath expression"):
            ApiSourceConfig(
                url="https://api.example.com",
                expression="[*",
            )

    def test_connect_timeout_exceeds_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"connect_timeout.*must not exceed.*timeout"):
            ApiSourceConfig(url="https://api.com", timeout=10.0, connect_timeout=30.0)

    def test_connect_timeout_equals_timeout_accepted(self) -> None:
        config = ApiSourceConfig(url="https://api.com", timeout=10.0, connect_timeout=10.0)
        assert config.connect_timeout == 10.0

    def test_allow_insecure_default_false(self) -> None:
        config = ApiSourceConfig(url="https://api.com")
        assert config.allow_insecure is False

    def test_allow_insecure_enabled(self) -> None:
        config = ApiSourceConfig(url="https://internal.api.com", allow_insecure=True)
        assert config.allow_insecure is True


class TestApiConfig:
    def test_default_values(self) -> None:
        config = ApiConfig()

        assert config.enabled is True
        assert len(config.sources) == 2
        assert config.request_delay == 1.0

    def test_default_sources(self) -> None:
        config = ApiConfig()

        urls = [s.url for s in config.sources]
        assert "https://api.nostr.watch/v1/online" in urls
        assert "https://api.nostr.watch/v1/offline" in urls

    def test_custom_sources(self) -> None:
        config = ApiConfig(
            sources=[
                ApiSourceConfig(url="https://custom1.api.com"),
                ApiSourceConfig(url="https://custom2.api.com"),
            ]
        )

        assert len(config.sources) == 2
        assert config.sources[0].url == "https://custom1.api.com"

    def test_max_response_size_default(self) -> None:
        config = ApiConfig()
        assert config.max_response_size == 5_242_880

    def test_max_response_size_custom(self) -> None:
        config = ApiConfig(max_response_size=1_048_576)
        assert config.max_response_size == 1_048_576

    def test_max_response_size_bounds(self) -> None:
        with pytest.raises(ValueError):
            ApiConfig(max_response_size=512)  # Below min (1024)

        with pytest.raises(ValueError):
            ApiConfig(max_response_size=100_000_000)  # Above max (50 MB)


class TestFinderConfig:
    def test_default_values(self) -> None:
        config = FinderConfig()

        assert config.interval == 300.0  # BaseServiceConfig default
        assert config.max_consecutive_failures == 5  # BaseServiceConfig default
        assert config.events.enabled is True
        assert config.api.enabled is True

    def test_custom_nested_config(self) -> None:
        config = FinderConfig(
            interval=7200.0,
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )

        assert config.interval == 7200.0
        assert config.events.enabled is False
        assert config.api.enabled is False

    def test_events_config(self) -> None:
        config = FinderConfig(
            events=EventsConfig(parallel_relays=15, max_relay_time=30.0, max_duration=120.0)
        )
        assert config.events.parallel_relays == 15
        assert config.events.max_relay_time == 30.0
        assert config.events.max_duration == 120.0


# ============================================================================
# Utils
# ============================================================================


class TestExtractRelaysFromResponse:
    # -- Default expression: [*] (flat string list) --------------------------

    def test_flat_string_list_default(self) -> None:
        data = ["wss://r1.com", "wss://r2.com"]
        relays = extract_relays_from_response(data)
        assert len(relays) == 2
        urls = {r.url for r in relays}
        assert "wss://r1.com" in urls
        assert "wss://r2.com" in urls

    def test_empty_list(self) -> None:
        assert extract_relays_from_response([]) == []

    def test_non_string_items_filtered(self) -> None:
        data = ["wss://r.com", 42, None, True]
        relays = extract_relays_from_response(data)
        assert len(relays) == 1
        assert relays[0].url == "wss://r.com"

    # -- Nested path expressions ---------------------------------------------

    def test_nested_path(self) -> None:
        data = {"data": {"relays": ["wss://r1.com", "wss://r2.com"]}}
        relays = extract_relays_from_response(data, "data.relays")
        assert len(relays) == 2

    def test_single_key_path(self) -> None:
        data = {"relays": ["wss://r1.com"]}
        relays = extract_relays_from_response(data, "relays")
        assert len(relays) == 1
        assert relays[0].url == "wss://r1.com"

    def test_nonexistent_path_returns_empty(self) -> None:
        data = {"other": ["wss://r1.com"]}
        assert extract_relays_from_response(data, "relays") == []

    # -- Object field extraction: [*].key ------------------------------------

    def test_extract_field_from_objects(self) -> None:
        data = [{"url": "wss://r1.com"}, {"url": "wss://r2.com"}]
        relays = extract_relays_from_response(data, "[*].url")
        assert len(relays) == 2

    def test_nested_path_then_field(self) -> None:
        data = {"data": [{"addr": "wss://r1.com"}, {"addr": "wss://r2.com"}]}
        relays = extract_relays_from_response(data, "data[*].addr")
        assert len(relays) == 2

    # -- Dict keys: keys(@) -------------------------------------------------

    def test_keys_extraction(self) -> None:
        data = {"wss://r1.com": {"info": "..."}, "wss://r2.com": {}}
        relays = extract_relays_from_response(data, "keys(@)")
        assert len(relays) == 2

    def test_nested_keys_extraction(self) -> None:
        data = {"data": {"wss://r1.com": {}}}
        relays = extract_relays_from_response(data, "keys(data)")
        assert len(relays) == 1
        assert relays[0].url == "wss://r1.com"

    # -- Edge cases ----------------------------------------------------------

    def test_none_data(self) -> None:
        assert extract_relays_from_response(None) == []

    def test_scalar_data(self) -> None:
        assert extract_relays_from_response(42) == []
        assert extract_relays_from_response("wss://r1.com") == []

    def test_expression_returns_non_list(self) -> None:
        data = {"count": 5}
        assert extract_relays_from_response(data, "count") == []

    def test_empty_dict_keys(self) -> None:
        assert extract_relays_from_response({}, "keys(@)") == []

    def test_invalid_urls_filtered(self) -> None:
        data = ["wss://valid.com", "http://wrong-scheme.com", "not-a-url"]
        relays = extract_relays_from_response(data)
        assert len(relays) == 1
        assert relays[0].url == "wss://valid.com"

    def test_deduplication(self) -> None:
        data = ["wss://relay.com", "wss://relay.com", "wss://relay.com"]
        relays = extract_relays_from_response(data)
        assert len(relays) == 1


class TestExtractRelaysFromTagvalues:
    def test_extracts_valid_relay_urls(self) -> None:
        rows = [
            {
                "tagvalues": [
                    "r:wss://relay1.example.com",
                    "r:wss://relay2.example.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)

        assert len(relays) == 2
        urls = {r.url for r in relays}
        assert any("relay1.example.com" in u for u in urls)
        assert any("relay2.example.com" in u for u in urls)

    def test_non_url_tag_values_rejected(self) -> None:
        rows = [
            {
                "tagvalues": [
                    "e:" + "a" * 64,  # hex event ID
                    "p:" + "b" * 64,  # hex pubkey
                    "t:bitcoin",  # hashtag
                    "t:nostr",  # hashtag
                    "r:wss://valid.relay.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)

        assert len(relays) == 1
        assert any("valid.relay.com" in r.url for r in relays)

    def test_extracts_relay_url_from_any_tag_prefix(self) -> None:
        rows = [
            {
                "tagvalues": [
                    "p:wss://relay-from-p-tag.com",
                    "e:wss://relay-from-e-tag.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)

        assert len(relays) == 2
        urls = {r.url for r in relays}
        assert any("relay-from-p-tag.com" in u for u in urls)
        assert any("relay-from-e-tag.com" in u for u in urls)

    def test_empty_rows(self) -> None:
        relays = extract_relays_from_tagvalues([])
        assert relays == []

    def test_none_tagvalues(self) -> None:
        rows = [{"tagvalues": None, "seen_at": 1700000000}]

        relays = extract_relays_from_tagvalues(rows)
        assert relays == []

    def test_empty_tagvalues(self) -> None:
        rows = [{"tagvalues": [], "seen_at": 1700000000}]

        relays = extract_relays_from_tagvalues(rows)
        assert relays == []

    def test_missing_tagvalues_key(self) -> None:
        rows = [{"seen_at": 1700000000}]

        relays = extract_relays_from_tagvalues(rows)
        assert relays == []

    def test_invalid_urls_skipped(self) -> None:
        rows = [
            {
                "tagvalues": [
                    "r:not-a-valid-url",
                    "r:http://wrong-scheme.com",
                    "t:",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)
        assert relays == []

    def test_deduplication_within_row(self) -> None:
        rows = [
            {
                "tagvalues": [
                    "r:wss://relay.example.com",
                    "r:wss://relay.example.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)
        assert len(relays) == 1

    def test_deduplication_across_rows(self) -> None:
        rows = [
            {"tagvalues": ["r:wss://relay.example.com"], "seen_at": 1700000000},
            {"tagvalues": ["r:wss://relay.example.com"], "seen_at": 1700000001},
        ]

        relays = extract_relays_from_tagvalues(rows)
        assert len(relays) == 1

    def test_mixed_valid_and_invalid(self) -> None:
        rows = [
            {
                "tagvalues": ["r:wss://good.relay.com", "e:" + "a" * 64],
                "seen_at": 1700000000,
            },
            {
                "tagvalues": ["t:bitcoin", "r:wss://another.relay.com"],
                "seen_at": 1700000001,
            },
            {
                "tagvalues": None,
                "seen_at": 1700000002,
            },
        ]

        relays = extract_relays_from_tagvalues(rows)

        assert len(relays) == 2
        urls = {r.url for r in relays}
        assert any("good.relay.com" in u for u in urls)
        assert any("another.relay.com" in u for u in urls)

    def test_ws_scheme_accepted(self) -> None:
        rows = [
            {
                "tagvalues": ["r:ws://clearnet.relay.com"],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)
        assert len(relays) == 1

    def test_tagvalue_without_prefix_skipped(self) -> None:
        rows = [
            {
                "tagvalues": ["no-prefix-here"],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_tagvalues(rows)
        assert relays == []


# ============================================================================
# Queries
# ============================================================================


class TestDeleteStaleCursors:
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


class TestDeleteStaleApiCheckpoints:
    async def test_deletes_inactive_sources(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=2)

        result = await delete_stale_api_checkpoints(query_brotr, ["https://active.example.com"])

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


class TestFetchEventRelayCursors:
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

    async def test_invalid_cursor_data_falls_back_to_empty(self, query_brotr: MagicMock) -> None:
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


class TestScanEventRelay:
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


class TestLoadApiCheckpoints:
    async def test_happy_path(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {"timestamp": 1700001000}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == [
            ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000),
            ApiCheckpoint(key="https://api2.example.com", timestamp=1700001000),
        ]

    async def test_skips_malformed(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == [ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000)]

    async def test_empty_urls(self, query_brotr: MagicMock) -> None:
        result = await load_api_checkpoints(query_brotr, [])

        assert result == []

    async def test_no_rows(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(return_value=[])
        urls = ["https://api.example.com"]

        result = await load_api_checkpoints(query_brotr, urls)

        assert result == []


class TestSaveApiCheckpoints:
    async def test_upserts_checkpoint_per_url(self, query_brotr: MagicMock) -> None:
        checkpoints = [
            ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000),
            ApiCheckpoint(key="https://api2.example.com", timestamp=1700001000),
        ]
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        await save_api_checkpoints(query_brotr, checkpoints)

        query_brotr.upsert_service_state.assert_awaited_once()
        records: list[ServiceState] = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        urls = {r.state_key for r in records}
        assert urls == {"https://api1.example.com", "https://api2.example.com"}
        by_key = {cp.key: cp.timestamp for cp in checkpoints}
        for r in records:
            assert r.service_name == ServiceName.FINDER
            assert r.state_type == ServiceStateType.CHECKPOINT
            assert r.state_value == {"timestamp": by_key[r.state_key]}


class TestSaveEventRelayCursor:
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


# ============================================================================
# Service
# ============================================================================


class TestFinderInit:
    def test_init_with_defaults(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)

        assert finder._brotr is mock_brotr
        assert finder.SERVICE_NAME == "finder"
        assert finder.config.api.enabled is True

    def test_init_with_custom_config(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(enabled=False),
            events=EventsConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        assert finder.config.api.enabled is False
        assert finder.config.events.enabled is False

    def test_from_dict(self, mock_brotr: Brotr) -> None:
        data = {
            "interval": 1800.0,
            "api": {"enabled": False},
            "events": {"enabled": False},
        }
        finder = Finder.from_dict(data, brotr=mock_brotr)

        assert finder.config.interval == 1800.0
        assert finder.config.api.enabled is False

    def test_service_name_class_attribute(self, mock_brotr: Brotr) -> None:
        assert Finder.SERVICE_NAME == "finder"

    def test_config_class_attribute(self, mock_brotr: Brotr) -> None:
        assert FinderConfig == Finder.CONFIG_CLASS


class TestFinderRun:
    async def test_run_all_disabled(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        await finder.run()

    async def test_run_calls_both_methods(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)

        with (
            patch.object(
                finder, "find_from_events", new_callable=AsyncMock, return_value=0
            ) as mock_events,
            patch.object(
                finder, "find_from_api", new_callable=AsyncMock, return_value=0
            ) as mock_api,
        ):
            await finder.run()

            mock_events.assert_called_once()
            mock_api.assert_called_once()


class TestFinderFindFromApi:
    async def test_find_from_api_all_sources_disabled(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api.example.com", enabled=False),
                ],
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.finder.service.load_api_checkpoints",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await finder.find_from_api()

        assert result == 0

    async def test_find_from_api_success(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 2
            mock_save.assert_awaited_once()

    async def test_find_from_api_handles_errors(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection failed"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 0

    async def test_find_from_api_skips_source_within_cooldown(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                cooldown=3600.0,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value=[
                    ApiCheckpoint(key="https://api.example.com", timestamp=int(time.time()) - 100)
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            result = await finder.find_from_api()

            assert result == 0
            mock_save.assert_not_awaited()

    async def test_find_from_api_fetches_source_past_cooldown(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                cooldown=3600.0,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        mock_response = _mock_api_response(["wss://relay1.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value=[
                    ApiCheckpoint(key="https://api.example.com", timestamp=int(time.time()) - 7200)
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 1
            mock_save.assert_awaited_once()


class TestFinderFetchSingleApi:
    async def test_fetch_single_api_valid_relays(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [r.url for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_filters_invalid_urls(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response(["wss://valid.relay.com", "invalid-url", "not-a-relay"])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 1
        result_urls = [r.url for r in result]
        assert "wss://valid.relay.com" in result_urls

    async def test_fetch_single_api_handles_non_list_response(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response({"relays": ["wss://relay.com"]})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0

    async def test_fetch_single_api_handles_empty_list(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response([])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0

    async def test_fetch_single_api_rejects_oversized_response(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(api=ApiConfig(max_response_size=1024))
        finder = Finder(brotr=mock_brotr, config=config)
        source = ApiSourceConfig(url="https://api.example.com")

        # Body larger than max_response_size (1024 bytes)
        oversized_body = b"x" * 1025
        content = MagicMock()
        content.read = AsyncMock(side_effect=[oversized_body, b""])
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.content = content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(ValueError, match="Response body too large"):
            await finder._fetch_single_api(mock_session, source)

    async def test_fetch_single_api_with_nested_path(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            expression="data.relays",
        )

        mock_response = _mock_api_response(
            {"data": {"relays": ["wss://relay1.com", "wss://relay2.com"]}}
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [r.url for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_with_field_extraction(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            expression="[*].address",
        )

        mock_response = _mock_api_response(
            [{"address": "wss://relay1.com"}, {"address": "wss://relay2.com"}]
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [r.url for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_with_keys_extraction(self, mock_brotr: Brotr) -> None:
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            expression="keys(@)",
        )

        mock_response = _mock_api_response(
            {"wss://relay1.com": {"uptime": 0.99}, "wss://relay2.com": {}}
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [r.url for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls


class TestFinderFindFromEvents:
    async def test_empty_database_returns_no_urls(self, mock_brotr: Brotr) -> None:
        mock_brotr._pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        result = await finder.find_from_events()

        assert result == 0

    async def test_valid_relay_urls_extracted_from_tagvalues(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 1

            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()
            all_urls = []
            for call in mock_insert.call_args_list:
                relays = call[0][1]
                for relay in relays:
                    all_urls.append(relay.url)
            assert any("relay.example.com" in url for url in all_urls)

    async def test_multiple_relay_urls_extracted(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay1.example.com", "r:wss://relay2.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 2

            mock_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()
            all_urls = []
            for call in mock_insert.call_args_list:
                relays = call[0][1]
                for relay in relays:
                    all_urls.append(relay.url)
            assert any("relay1.example.com" in url for url in all_urls)
            assert any("relay2.example.com" in url for url in all_urls)

    async def test_non_url_tagvalues_filtered_out(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://rtag-relay.com", "e:" + "a" * 64, "t:bitcoin"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 1

            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()
            all_urls = []
            for call in mock_insert.call_args_list:
                relays = call[0][1]
                for relay in relays:
                    all_urls.append(relay.url)
            assert any("rtag-relay.com" in url for url in all_urls)

    async def test_invalid_malformed_urls_filtered_out(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:not-a-valid-url", "r:http://wrong-scheme.com", "r:also-not-valid"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 0

            mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            result = await finder.find_from_events()

            assert result == 0

    async def test_duplicate_urls_deduplicated(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": [
                "r:wss://duplicate.relay.com",
                "r:wss://duplicate.relay.com",
                "r:wss://duplicate.relay.com",
            ],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 1

            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            # Three duplicate URLs should collapse to a single relay object
            mock_insert.assert_called()
            relays = list(mock_insert.call_args_list[0][0][1])
            assert len(relays) == 1
            assert relays[0].url == "wss://duplicate.relay.com"

    async def test_cursor_position_updated_after_scan(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay.example.com"],
            "seen_at": 1700000200,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 1

            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            upsert_calls = mock_brotr.upsert_service_state.call_args_list
            cursor_saved = any(
                call[0][0]
                and call[0][0][0].service_name == "finder"
                and call[0][0][0].state_type == "cursor"
                for call in upsert_calls
            )
            assert cursor_saved

    async def test_exception_handling_during_database_query(self, mock_brotr: Brotr) -> None:
        mock_brotr._pool.fetch = AsyncMock(side_effect=OSError("Database connection error"))  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        result = await finder.find_from_events()

        assert result == 0

    async def test_network_type_detected_clearnet_vs_tor(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://clearnet.relay.com", "r:ws://tortest.onion"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [
                EventRelayCursor(relay_url="wss://source.relay.com"),
            ]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 2

            mock_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()


class TestFinderEventScanConcurrency:
    async def test_multiple_relays_scanned_concurrently(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://found.relay.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        # Track per-relay call counts so side_effect works under concurrency
        call_counts: dict[str, int] = {}

        async def _events_side_effect(
            brotr: Any,
            cursor: EventRelayCursor,
            limit: int,
        ) -> list[dict[str, Any]]:
            count = call_counts.get(cursor.relay_url, 0)
            call_counts[cursor.relay_url] = count + 1
            if count == 0:
                return [mock_event]
            return []

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors",
                new_callable=AsyncMock,
                return_value=[
                    EventRelayCursor(relay_url="wss://relay1.com"),
                    EventRelayCursor(relay_url="wss://relay2.com"),
                    EventRelayCursor(relay_url="wss://relay3.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=_events_side_effect,
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            config = FinderConfig(
                events=EventsConfig(parallel_relays=10),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 3
            finder.set_gauge.assert_any_call("relays_scanned", 3)

    async def test_task_failure_does_not_block_others(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://found.relay.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        async def _events_side_effect(
            brotr: Any,
            cursor: EventRelayCursor,
            limit: int,
        ) -> list[dict[str, Any]]:
            if cursor.relay_url == "wss://failing.relay.com" and cursor.seen_at is None:
                raise asyncpg.PostgresError("simulated DB error")
            if cursor.seen_at is not None:
                return []
            return [mock_event]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors",
                new_callable=AsyncMock,
                return_value=[
                    EventRelayCursor(relay_url="wss://good.relay.com"),
                    EventRelayCursor(relay_url="wss://failing.relay.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=_events_side_effect,
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            # _scan_relay_events catches DB errors internally: the failing relay
            # returns (0, 0) and the good relay returns (1, 1). Both tasks
            # complete without exception, so both count as processed.
            assert result == 1
            finder.set_gauge.assert_any_call("relays_scanned", 2)

    async def test_semaphore_limits_concurrency(self, mock_brotr: Brotr) -> None:
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        original_scan = Finder._scan_relay_events

        async def _tracking_scan(self: Any, cursor: EventRelayCursor) -> tuple[int, int]:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            try:
                return await original_scan(self, cursor)
            finally:
                async with lock:
                    current_concurrent -= 1

        cursors = [EventRelayCursor(relay_url=f"wss://relay{i}.com") for i in range(20)]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors",
                new_callable=AsyncMock,
                return_value=cursors,
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(Finder, "_scan_relay_events", _tracking_scan),
        ):
            config = FinderConfig(
                events=EventsConfig(parallel_relays=3),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            assert max_concurrent <= 3


class TestParseRelayUrl:
    def test_parse_valid_wss_url(self) -> None:
        result = parse_relay("wss://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_parse_valid_ws_url(self) -> None:
        result = parse_relay("ws://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_parse_invalid_url(self) -> None:
        assert parse_relay("not-a-url") is None
        assert parse_relay("http://wrong-scheme.com") is None
        assert parse_relay("") is None
        assert parse_relay(None) is None  # type: ignore[arg-type]

    def test_parse_tor_url(self) -> None:
        result = parse_relay("ws://example.onion")

        assert result is not None
        assert "onion" in result.url

    def test_parse_i2p_url(self) -> None:
        result = parse_relay("ws://example.i2p")

        assert result is not None
        assert "i2p" in result.url

    def test_parse_strips_whitespace(self) -> None:
        result = parse_relay("  wss://relay.example.com  ")

        assert result is not None
        assert result.url == "wss://relay.example.com"


# ============================================================================
# Metrics
# ============================================================================


class TestFinderMetrics:
    async def test_find_from_events_emits_gauges_and_counters(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay1.example.com", "r:wss://relay2.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors",
                new_callable=AsyncMock,
                return_value=[
                    EventRelayCursor(relay_url="wss://source.relay.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=[[mock_event], []],
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            finder.set_gauge.assert_any_call("event_candidates", 2)
            finder.set_gauge.assert_any_call("relays_scanned", 1)
            finder.inc_counter.assert_any_call("total_event_candidates", 2)
            finder.inc_counter.assert_any_call("total_events_processed", 1)

    async def test_find_from_events_disabled_no_metrics(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(events=EventsConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_counter = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_events()

        assert result == 0
        finder.set_gauge.assert_not_called()
        finder.inc_counter.assert_not_called()

    async def test_find_from_api_emits_gauge(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            await finder.find_from_api()

            finder.set_gauge.assert_any_call("api_candidates", 2)

    async def test_find_from_api_disabled_no_metrics(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(api=ApiConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_api()

        assert result == 0
        finder.set_gauge.assert_not_called()

    async def test_find_from_api_emits_counter(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_counter = MagicMock()  # type: ignore[method-assign]
        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.load_api_checkpoints",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.save_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            await finder.find_from_api()

            finder.inc_counter.assert_any_call("total_api_candidates", 2)

    async def test_find_from_events_unexpected_error_counted(self, mock_brotr: Brotr) -> None:
        async def _failing_events(
            brotr: Any,
            cursor: EventRelayCursor,
            limit: int,
        ) -> list[dict[str, Any]]:
            if cursor.relay_url == "wss://bad.relay.com":
                raise RuntimeError("unexpected error")
            return []

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_event_relay_cursors",
                new_callable=AsyncMock,
                return_value=[
                    EventRelayCursor(relay_url="wss://good.relay.com"),
                    EventRelayCursor(relay_url="wss://bad.relay.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=_failing_events,
            ),
        ):
            finder = Finder(brotr=mock_brotr)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            # RuntimeError caught by _bounded_scan, pushes (0, 0) to queue.
            # Both relays are counted as scanned.
            finder.set_gauge.assert_any_call("relays_scanned", 2)


# ============================================================================
# Cleanup
# ============================================================================


class TestFinderCleanup:
    async def test_cleanup_removes_orphaned_cursors_and_stale_checkpoints(
        self, mock_brotr: Brotr
    ) -> None:
        mock_brotr.fetchval = AsyncMock(side_effect=[3, 2])
        finder = Finder(brotr=mock_brotr)
        result = await finder.cleanup()
        assert mock_brotr.fetchval.await_count == 2
        cursor_sql = mock_brotr.fetchval.call_args_list[0][0][0]
        checkpoint_sql = mock_brotr.fetchval.call_args_list[1][0][0]
        assert "NOT EXISTS" in cursor_sql
        assert "NOT (state_key = ANY" in checkpoint_sql
        assert result == 5
