"""Unit tests for the finder service package."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import aiohttp
import asyncpg
import pytest
from pydantic import ValidationError

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.types import ApiCheckpoint, FinderCursor
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
    fetch_api_checkpoints,
    fetch_cursors_to_find,
    scan_event_relay,
    upsert_api_checkpoints,
    upsert_finder_cursors,
)
from bigbrotr.services.finder.utils import (
    extract_relays_from_response,
    extract_relays_from_tagvalues,
    fetch_api,
    stream_event_relays,
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


def _default_checkpoints(config: FinderConfig) -> list[ApiCheckpoint]:
    return [ApiCheckpoint(key=s.url, timestamp=0) for s in config.api.sources]


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


async def _mock_stream(*rows: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
    """Create an async generator that yields the given rows."""
    for row in rows:
        yield row


# ============================================================================
# Configs
# ============================================================================


class TestEventsConfig:
    def test_default_values(self) -> None:
        config = EventsConfig()
        assert config.enabled is True
        assert config.batch_size == 500
        assert config.parallel_relays == 60
        assert config.max_relay_time == 900.0
        assert config.max_duration == 7200.0

    def test_disabled(self) -> None:
        config = EventsConfig(enabled=False)
        assert config.enabled is False

    @pytest.mark.parametrize(
        ("field", "valid_min", "valid_max", "below_min", "above_max"),
        [
            ("batch_size", 10, 10_000, 5, 10_001),
            ("parallel_relays", 1, 200, 0, 201),
        ],
    )
    def test_integer_field_bounds(
        self, field: str, valid_min: int, valid_max: int, below_min: int, above_max: int
    ) -> None:
        assert getattr(EventsConfig(**{field: valid_min}), field) == valid_min
        assert getattr(EventsConfig(**{field: valid_max}), field) == valid_max
        with pytest.raises(ValueError):
            EventsConfig(**{field: below_min})
        with pytest.raises(ValueError):
            EventsConfig(**{field: above_max})

    @pytest.mark.parametrize(
        ("field", "valid", "below_min", "above_max"),
        [
            ("max_relay_time", 30.0, 5.0, 86_401.0),
            ("max_duration", 120.0, 30.0, 86_401.0),
        ],
    )
    def test_float_field_bounds(
        self, field: str, valid: float, below_min: float, above_max: float
    ) -> None:
        assert getattr(EventsConfig(**{field: valid}), field) == valid
        with pytest.raises(ValueError):
            EventsConfig(**{field: below_min})
        with pytest.raises(ValueError):
            EventsConfig(**{field: above_max})


class TestApiSourceConfig:
    def test_default_values(self) -> None:
        config = ApiSourceConfig(url="https://api.example.com", expression="[*]")

        assert config.url == "https://api.example.com"
        assert config.enabled is True
        assert config.timeout == 30.0
        assert config.expression == "[*]"
        assert config.allow_insecure is False

    def test_expression_required(self) -> None:
        with pytest.raises(ValidationError):
            ApiSourceConfig(url="https://api.example.com")

    def test_custom_values(self) -> None:
        config = ApiSourceConfig(
            url="https://custom.api.com",
            enabled=False,
            timeout=60.0,
            expression="[*]",
        )

        assert config.url == "https://custom.api.com"
        assert config.enabled is False
        assert config.timeout == 60.0

    def test_timeout_bounds(self) -> None:
        config_min = ApiSourceConfig(
            url="https://api.com", expression="[*]", timeout=0.1, connect_timeout=0.1
        )
        assert config_min.timeout == 0.1

        config_max = ApiSourceConfig(url="https://api.com", expression="[*]", timeout=120.0)
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
            ApiSourceConfig(
                url="https://api.com", expression="[*]", timeout=10.0, connect_timeout=30.0
            )

    def test_connect_timeout_equals_timeout_accepted(self) -> None:
        config = ApiSourceConfig(
            url="https://api.com", expression="[*]", timeout=10.0, connect_timeout=10.0
        )
        assert config.connect_timeout == 10.0

    def test_allow_insecure_enabled(self) -> None:
        config = ApiSourceConfig(
            url="https://internal.api.com", expression="[*]", allow_insecure=True
        )
        assert config.allow_insecure is True


class TestApiConfig:
    def test_default_values(self) -> None:
        config = ApiConfig()

        assert config.enabled is True
        assert len(config.sources) == 2
        assert config.request_delay == 1.0
        assert config.max_response_size == 5_242_880

    def test_default_sources(self) -> None:
        config = ApiConfig()

        urls = [s.url for s in config.sources]
        assert "https://api.nostr.watch/v1/online" in urls
        assert "https://api.nostr.watch/v1/offline" in urls

    def test_custom_sources(self) -> None:
        config = ApiConfig(
            sources=[
                ApiSourceConfig(url="https://custom1.api.com", expression="[*]"),
                ApiSourceConfig(url="https://custom2.api.com", expression="[*]"),
            ]
        )

        assert len(config.sources) == 2
        assert config.sources[0].url == "https://custom1.api.com"

    @pytest.mark.parametrize(
        ("size", "should_fail"),
        [
            (1_048_576, False),
            (512, True),
            (100_000_000, True),
        ],
    )
    def test_max_response_size_bounds(self, size: int, should_fail: bool) -> None:
        if should_fail:
            with pytest.raises(ValueError):
                ApiConfig(max_response_size=size)
        else:
            assert ApiConfig(max_response_size=size).max_response_size == size


class TestFinderConfig:
    def test_default_values(self) -> None:
        config = FinderConfig()

        assert config.interval == 300.0
        assert config.max_consecutive_failures == 5
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
    def test_flat_string_list(self) -> None:
        data = ["wss://r1.com", "wss://r2.com"]
        relays = extract_relays_from_response(data, "[*]")
        assert len(relays) == 2
        urls = {r.url for r in relays}
        assert "wss://r1.com" in urls
        assert "wss://r2.com" in urls

    def test_empty_list(self) -> None:
        assert extract_relays_from_response([], "[*]") == []

    def test_non_string_items_filtered(self) -> None:
        data = ["wss://r.com", 42, None, True]
        relays = extract_relays_from_response(data, "[*]")
        assert len(relays) == 1
        assert relays[0].url == "wss://r.com"

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

    def test_extract_field_from_objects(self) -> None:
        data = [{"url": "wss://r1.com"}, {"url": "wss://r2.com"}]
        relays = extract_relays_from_response(data, "[*].url")
        assert len(relays) == 2

    def test_nested_path_then_field(self) -> None:
        data = {"data": [{"addr": "wss://r1.com"}, {"addr": "wss://r2.com"}]}
        relays = extract_relays_from_response(data, "data[*].addr")
        assert len(relays) == 2

    def test_keys_extraction(self) -> None:
        data = {"wss://r1.com": {"info": "..."}, "wss://r2.com": {}}
        relays = extract_relays_from_response(data, "keys(@)")
        assert len(relays) == 2

    def test_nested_keys_extraction(self) -> None:
        data = {"data": {"wss://r1.com": {}}}
        relays = extract_relays_from_response(data, "keys(data)")
        assert len(relays) == 1
        assert relays[0].url == "wss://r1.com"

    @pytest.mark.parametrize(
        "data",
        [None, 42, "wss://r1.com"],
        ids=["none", "scalar", "string"],
    )
    def test_non_list_data_returns_empty(self, data: Any) -> None:
        assert extract_relays_from_response(data, "[*]") == []

    def test_expression_returns_non_list(self) -> None:
        data = {"count": 5}
        assert extract_relays_from_response(data, "count") == []

    def test_empty_dict_keys(self) -> None:
        assert extract_relays_from_response({}, "keys(@)") == []

    def test_invalid_urls_filtered(self) -> None:
        data = ["wss://valid.com", "http://wrong-scheme.com", "not-a-url"]
        relays = extract_relays_from_response(data, "[*]")
        assert len(relays) == 1
        assert relays[0].url == "wss://valid.com"

    def test_deduplication(self) -> None:
        data = ["wss://relay.com", "wss://relay.com", "wss://relay.com"]
        relays = extract_relays_from_response(data, "[*]")
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
                    "e:" + "a" * 64,
                    "p:" + "b" * 64,
                    "t:bitcoin",
                    "t:nostr",
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

    def test_non_string_tagvalue_skipped(self) -> None:
        rows = [{"tagvalues": [42, None, True], "seen_at": 1700000000}]
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


class TestFetchFinderCursors:
    async def test_returns_cursor_for_relay_with_state(self, query_brotr: MagicMock) -> None:
        rows = [
            _make_dict_row(
                {
                    "url": "wss://relay.com",
                    "state_value": {"timestamp": 1700000000, "id": "ab" * 32},
                }
            ),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_cursors_to_find(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.key == "wss://relay.com"
        assert cursor.timestamp == 1700000000
        assert cursor.id == "ab" * 32

    async def test_returns_empty_cursor_for_relay_without_state(
        self, query_brotr: MagicMock
    ) -> None:
        rows = [
            _make_dict_row({"url": "wss://new.relay.com", "state_value": None}),
        ]
        query_brotr.fetch = AsyncMock(return_value=rows)

        result = await fetch_cursors_to_find(query_brotr)

        assert len(result) == 1
        cursor = result[0]
        assert cursor.key == "wss://new.relay.com"
        assert cursor.timestamp == 0
        assert cursor.id == "0" * 64

    async def test_query_uses_left_join(self, query_brotr: MagicMock) -> None:
        await fetch_cursors_to_find(query_brotr)

        query_brotr.fetch.assert_awaited_once()
        sql = query_brotr.fetch.call_args[0][0]
        assert "LEFT JOIN cursors" in sql
        assert "FROM relay" in sql

    async def test_empty_database(self, query_brotr: MagicMock) -> None:
        result = await fetch_cursors_to_find(query_brotr)

        assert result == []


class TestScanEventRelay:
    async def test_scan_with_cursor(self, query_brotr: MagicMock) -> None:
        event_id = "ab" * 32
        cursor = FinderCursor(
            key="wss://source.relay.com",
            timestamp=1700000000,
            id=event_id,
        )
        await scan_event_relay(query_brotr, cursor, limit=500)

        query_brotr.fetch.assert_awaited_once()
        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "FROM event e" in sql
        assert "event_relay er" in sql
        assert "relay_url = $1" in sql
        assert "(er.seen_at, e.id) >" in sql
        assert "LIMIT $4" in sql
        assert args[0][1] == "wss://source.relay.com"
        assert args[0][2] == 1700000000
        assert args[0][3] == event_id
        assert args[0][4] == 500

    async def test_scan_default_cursor(self, query_brotr: MagicMock) -> None:
        cursor = FinderCursor(key="wss://source.relay.com")
        await scan_event_relay(query_brotr, cursor, limit=100)

        args = query_brotr.fetch.call_args
        assert args[0][2] == 0
        assert args[0][3] == "0" * 64

    async def test_scan_empty(self, query_brotr: MagicMock) -> None:
        cursor = FinderCursor(key="wss://source.relay.com")
        result = await scan_event_relay(query_brotr, cursor, limit=100)

        assert result == []


class TestFetchApiCheckpoints:
    async def test_happy_path(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {"timestamp": 1700001000}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await fetch_api_checkpoints(query_brotr, urls)

        assert result == [
            ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000),
            ApiCheckpoint(key="https://api2.example.com", timestamp=1700001000),
        ]

    async def test_malformed_defaults_to_zero(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api1.example.com", "state_value": {"timestamp": 1700000000}},
                {"state_key": "https://api2.example.com", "state_value": {}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com"]

        result = await fetch_api_checkpoints(query_brotr, urls)

        assert result == [
            ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000),
            ApiCheckpoint(key="https://api2.example.com", timestamp=0),
        ]

    async def test_empty_urls(self, query_brotr: MagicMock) -> None:
        result = await fetch_api_checkpoints(query_brotr, [])

        assert result == []

    async def test_missing_url_defaults_to_zero(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(return_value=[])
        urls = ["https://api.example.com"]

        result = await fetch_api_checkpoints(query_brotr, urls)

        assert result == [ApiCheckpoint(key="https://api.example.com", timestamp=0)]

    async def test_preserves_url_order(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {"state_key": "https://api2.example.com", "state_value": {"timestamp": 2000}},
            ]
        )
        urls = ["https://api1.example.com", "https://api2.example.com", "https://api3.example.com"]

        result = await fetch_api_checkpoints(query_brotr, urls)

        assert result == [
            ApiCheckpoint(key="https://api1.example.com", timestamp=0),
            ApiCheckpoint(key="https://api2.example.com", timestamp=2000),
            ApiCheckpoint(key="https://api3.example.com", timestamp=0),
        ]


class TestSaveApiCheckpoints:
    async def test_upserts_checkpoint_per_url(self, query_brotr: MagicMock) -> None:
        checkpoints = [
            ApiCheckpoint(key="https://api1.example.com", timestamp=1700000000),
            ApiCheckpoint(key="https://api2.example.com", timestamp=1700001000),
        ]
        query_brotr.upsert_service_state = AsyncMock(return_value=2)

        await upsert_api_checkpoints(query_brotr, checkpoints)

        query_brotr.upsert_service_state.assert_awaited_once()
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 2
        urls = {r.state_key for r in records}
        assert urls == {"https://api1.example.com", "https://api2.example.com"}
        by_key = {cp.key: cp.timestamp for cp in checkpoints}
        for r in records:
            assert r.service_name == ServiceName.FINDER
            assert r.state_type == ServiceStateType.CHECKPOINT
            assert r.state_value == {"timestamp": by_key[r.state_key]}


class TestSaveFinderCursors:
    async def test_upserts_multiple_cursors(self, query_brotr: MagicMock) -> None:
        cursors = [
            FinderCursor(key="wss://relay1.example.com", timestamp=100, id="ab" * 32),
            FinderCursor(key="wss://relay2.example.com", timestamp=200, id="cd" * 32),
        ]
        await upsert_finder_cursors(query_brotr, cursors)

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 2
        assert states[0].state_key == "wss://relay1.example.com"
        assert states[0].state_value["timestamp"] == 100
        assert states[1].state_key == "wss://relay2.example.com"
        assert states[1].state_value["timestamp"] == 200

    async def test_blank_cursors_skipped(self, query_brotr: MagicMock) -> None:
        cursors = [
            FinderCursor(key="wss://relay1.example.com"),
            FinderCursor(key="wss://relay2.example.com", timestamp=200, id="cd" * 32),
        ]
        await upsert_finder_cursors(query_brotr, cursors)

        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 1
        assert states[0].state_key == "wss://relay2.example.com"

    async def test_all_blank_is_noop(self, query_brotr: MagicMock) -> None:
        await upsert_finder_cursors(query_brotr, [FinderCursor(key="wss://relay.example.com")])

        query_brotr.upsert_service_state.assert_not_awaited()

    async def test_empty_list_is_noop(self, query_brotr: MagicMock) -> None:
        await upsert_finder_cursors(query_brotr, [])

        query_brotr.upsert_service_state.assert_not_awaited()


# ============================================================================
# Service Init
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


# ============================================================================
# Main Methods
# ============================================================================


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
    async def test_api_disabled_returns_zero(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(api=ApiConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_api()

        assert result == 0
        finder.set_gauge.assert_not_called()

    async def test_all_sources_disabled(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api.example.com", expression="[*]", enabled=False),
                ],
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with patch(
            "bigbrotr.services.finder.service.fetch_api_checkpoints",
            new_callable=AsyncMock,
            return_value=_default_checkpoints(config),
        ):
            result = await finder.find_from_api()

        assert result == 0

    async def test_success(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com", expression="[*]")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
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

    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ClientError("Connection failed"),
            TimeoutError("Timed out"),
            OSError("Network error"),
        ],
        ids=["client_error", "timeout", "os_error"],
    )
    async def test_handles_fetch_errors(self, mock_brotr: Brotr, error: Exception) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com", expression="[*]")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=error)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 0

    async def test_skips_source_within_cooldown(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                cooldown=3600.0,
                sources=[ApiSourceConfig(url="https://api.example.com", expression="[*]")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=[
                    ApiCheckpoint(key="https://api.example.com", timestamp=int(time.time()) - 100)
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            result = await finder.find_from_api()

            assert result == 0
            mock_save.assert_not_awaited()

    async def test_fetches_source_past_cooldown(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                cooldown=3600.0,
                sources=[ApiSourceConfig(url="https://api.example.com", expression="[*]")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        mock_response = _mock_api_response(["wss://relay1.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=[
                    ApiCheckpoint(key="https://api.example.com", timestamp=int(time.time()) - 7200)
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
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

    async def test_shutdown_during_iteration_stops(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
                    ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
                ],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.com")

        async def _fetch_and_shutdown(
            session: Any, source: Any, max_response_size: Any
        ) -> list[Relay]:
            finder.request_shutdown()
            return [relay]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch("bigbrotr.services.finder.service.fetch_api", side_effect=_fetch_and_shutdown),
        ):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 1

    async def test_request_delay_shutdown_stops_iteration(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
                    ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
                ],
                request_delay=1.0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        relay = Relay("wss://relay.com")

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "bigbrotr.services.finder.service.fetch_api",
                new_callable=AsyncMock,
                return_value=[relay],
            ) as mock_fetch_api,
        ):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            async def _wait_returns_true(delay: float) -> bool:
                return True

            finder.wait = _wait_returns_true  # type: ignore[method-assign]

            result = await finder.find_from_api()

            assert result == 1
            assert mock_fetch_api.call_count == 1

    async def test_passes_all_relays_to_insert(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
                    ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
                ],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        mock_resp1 = _mock_api_response(["wss://relay.com", "wss://unique1.com"])
        mock_resp2 = _mock_api_response(["wss://relay.com", "wss://unique2.com"])

        call_count = 0

        def _get_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_resp1 if call_count == 1 else mock_resp2

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
                new_callable=AsyncMock,
            ),
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
            ) as mock_insert,
        ):
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=_get_side_effect)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session
            mock_insert.return_value = 4

            await finder.find_from_api()

            relays = mock_insert.call_args[0][1]
            assert len(relays) == 4

    async def test_emits_gauge_and_counter(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com", expression="[*]")],
                request_delay=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_gauge = MagicMock()  # type: ignore[method-assign]
        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_api_checkpoints",
                new_callable=AsyncMock,
                return_value=_default_checkpoints(config),
            ),
            patch(
                "bigbrotr.services.finder.service.upsert_api_checkpoints",
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

            finder.inc_gauge.assert_any_call("sources_fetched")
            finder.set_gauge.assert_any_call("total_sources", 1)


class TestFetchApi:
    async def test_valid_relays(self) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")

        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await fetch_api(mock_session, source, 5_242_880)

        assert len(result) == 2
        result_urls = [r.url for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_empty_list(self) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")

        mock_response = _mock_api_response([])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await fetch_api(mock_session, source, 5_242_880)

        assert len(result) == 0

    async def test_rejects_oversized_response(self) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")

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
            await fetch_api(mock_session, source, 1024)

    async def test_passes_ssl_flag_from_allow_insecure(self) -> None:
        source = ApiSourceConfig(
            url="https://api.example.com", expression="[*]", allow_insecure=True
        )

        mock_response = _mock_api_response([])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        await fetch_api(mock_session, source, 5_242_880)

        _, kwargs = mock_session.get.call_args
        assert kwargs["ssl"] is False


class TestStreamEventRelays:
    async def test_empty_result_yields_nothing(self) -> None:
        brotr = MagicMock()
        cursor = FinderCursor(key="wss://relay.com")
        with patch(
            "bigbrotr.services.finder.utils.scan_event_relay",
            new_callable=AsyncMock,
            return_value=[],
        ):
            rows = [row async for row in stream_event_relays(brotr, cursor, 100)]

        assert rows == []

    async def test_single_batch_partial(self) -> None:
        event_id = b"\xab" * 32
        batch = [
            {"event_id": event_id, "seen_at": 1700000001, "tagvalues": ["r:wss://r.com"]},
            {"event_id": event_id, "seen_at": 1700000002, "tagvalues": ["r:wss://r2.com"]},
        ]
        brotr = MagicMock()
        cursor = FinderCursor(key="wss://relay.com")
        with patch(
            "bigbrotr.services.finder.utils.scan_event_relay",
            new_callable=AsyncMock,
            return_value=batch,
        ) as mock_scan:
            rows = [row async for row in stream_event_relays(brotr, cursor, 100)]

        assert len(rows) == 2
        assert rows[0]["seen_at"] == 1700000001
        assert rows[1]["seen_at"] == 1700000002
        mock_scan.assert_awaited_once()

    async def test_multi_batch_pagination(self) -> None:
        id1 = b"\x01" * 32
        id2 = b"\x02" * 32
        batch1 = [
            {"event_id": id1, "seen_at": 100, "tagvalues": []},
            {"event_id": id2, "seen_at": 200, "tagvalues": []},
        ]
        batch2 = [{"event_id": id1, "seen_at": 300, "tagvalues": []}]
        brotr = MagicMock()
        cursor = FinderCursor(key="wss://relay.com")
        with patch(
            "bigbrotr.services.finder.utils.scan_event_relay",
            new_callable=AsyncMock,
            side_effect=[batch1, batch2],
        ) as mock_scan:
            rows = [row async for row in stream_event_relays(brotr, cursor, 2)]

        assert len(rows) == 3
        assert mock_scan.await_count == 2
        second_call_cursor = mock_scan.call_args_list[1][0][1]
        assert second_call_cursor.timestamp == 200
        assert second_call_cursor.id == id2.hex()

    async def test_exact_batch_size_triggers_next_fetch(self) -> None:
        id1 = b"\xaa" * 32
        batch1 = [{"event_id": id1, "seen_at": 100, "tagvalues": []}]
        brotr = MagicMock()
        cursor = FinderCursor(key="wss://relay.com")
        with patch(
            "bigbrotr.services.finder.utils.scan_event_relay",
            new_callable=AsyncMock,
            side_effect=[batch1, []],
        ) as mock_scan:
            rows = [row async for row in stream_event_relays(brotr, cursor, 1)]

        assert len(rows) == 1
        assert mock_scan.await_count == 2

    async def test_cursor_key_preserved_across_batches(self) -> None:
        id1 = b"\x01" * 32
        batch1 = [{"event_id": id1, "seen_at": 100, "tagvalues": []}]
        brotr = MagicMock()
        cursor = FinderCursor(key="wss://specific.relay.com")
        with patch(
            "bigbrotr.services.finder.utils.scan_event_relay",
            new_callable=AsyncMock,
            side_effect=[batch1, []],
        ) as mock_scan:
            [row async for row in stream_event_relays(brotr, cursor, 1)]

        for call in mock_scan.call_args_list:
            assert call[0][1].key == "wss://specific.relay.com"


# ============================================================================
# Event Workers
# ============================================================================


class TestFinderFindFromEvents:
    async def test_disabled_returns_zero(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(events=EventsConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_events()

        assert result == 0
        finder.set_gauge.assert_not_called()

    async def test_empty_database_returns_zero(self, mock_brotr: Brotr) -> None:
        mock_brotr._pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        result = await finder.find_from_events()

        assert result == 0

    async def test_valid_relay_urls_extracted(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[FinderCursor(key="wss://source.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                return_value=_mock_stream(mock_event),
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_insert,
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()
            all_urls = [r.url for call in mock_insert.call_args_list for r in call[0][1]]
            assert any("relay.example.com" in url for url in all_urls)

    async def test_cursor_position_updated_after_scan(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay.example.com"],
            "seen_at": 1700000200,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[FinderCursor(key="wss://source.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                return_value=_mock_stream(mock_event),
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
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

    async def test_buffer_flushed_mid_loop_when_exceeds_batch_size(self, mock_brotr: Brotr) -> None:
        events = [
            {
                "tagvalues": [f"r:wss://relay{i}.example.com"],
                "seen_at": 1700000000 + i,
                "event_id": bytes([i]) + b"\x00" * 31,
            }
            for i in range(25)
        ]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[FinderCursor(key="wss://source.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                return_value=_mock_stream(*events),
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                side_effect=lambda _b, relays: len(relays),
            ) as mock_insert,
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            config = FinderConfig(events=EventsConfig(batch_size=10))
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 25
            assert mock_insert.call_count >= 2

    async def test_phase_duration_exceeded_stops_workers(self, mock_brotr: Brotr) -> None:
        config = FinderConfig(events=EventsConfig(max_duration=60))
        finder = Finder(brotr=mock_brotr, config=config)
        finder._phase_start = 0.0
        finder._event_semaphore = asyncio.Semaphore(50)

        with patch("time.monotonic", return_value=61.0):
            items = [
                item
                async for item in finder._find_from_events_worker(
                    FinderCursor(key="wss://relay1.com")
                )
            ]

        assert items == []

    async def test_per_relay_deadline_exceeded_stops_worker(self, mock_brotr: Brotr) -> None:
        events = [
            {
                "tagvalues": [f"r:wss://relay{i}.example.com"],
                "seen_at": 1700000000 + i,
                "event_id": bytes([i]) + b"\x00" * 31,
            }
            for i in range(3)
        ]
        config = FinderConfig(events=EventsConfig(max_relay_time=10.0, max_duration=7200))
        finder = Finder(brotr=mock_brotr, config=config)
        finder._phase_start = time.monotonic()
        finder._event_semaphore = asyncio.Semaphore(50)

        monotonic_calls = iter([100.0, 100.0, 100.0, 111.0])

        with (
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                return_value=_mock_stream(*events),
            ),
            patch(
                "bigbrotr.services.finder.service.time.monotonic",
                side_effect=monotonic_calls,
            ),
        ):
            items = [
                item
                async for item in finder._find_from_events_worker(
                    FinderCursor(key="wss://source.relay.com")
                )
            ]

        assert len(items) < 3

    async def test_emits_gauges_and_counters(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://relay1.example.com", "r:wss://relay2.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[FinderCursor(key="wss://source.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                return_value=_mock_stream(mock_event),
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
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            finder.inc_gauge.assert_any_call("rows_seen")
            finder.inc_gauge.assert_any_call("relays_seen")


class TestFinderEventScanConcurrency:
    async def test_multiple_relays_scanned_concurrently(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://found.relay.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[
                    FinderCursor(key="wss://relay1.com"),
                    FinderCursor(key="wss://relay2.com"),
                    FinderCursor(key="wss://relay3.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                side_effect=lambda *_args: _mock_stream(mock_event),
            ),
            patch(
                "bigbrotr.services.finder.service.insert_relays_as_candidates",
                new_callable=AsyncMock,
                side_effect=lambda _b, relays: len(relays),
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            config = FinderConfig(
                events=EventsConfig(parallel_relays=10),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 3
            relays_seen_calls = [
                c for c in finder.inc_gauge.call_args_list if c.args[0] == "relays_seen"
            ]
            assert len(relays_seen_calls) == 3

    async def test_task_failure_does_not_block_others(self, mock_brotr: Brotr) -> None:
        mock_event = {
            "tagvalues": ["r:wss://found.relay.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        async def _failing_stream(
            brotr: Any,
            cursor: FinderCursor,
            batch_size: int,
        ) -> AsyncGenerator[dict[str, Any], None]:
            if cursor.key == "wss://failing.relay.com":
                raise asyncpg.PostgresError("simulated DB error")
            yield mock_event

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[
                    FinderCursor(key="wss://good.relay.com"),
                    FinderCursor(key="wss://failing.relay.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                side_effect=_failing_stream,
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
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 1
            finder.inc_gauge.assert_any_call("relays_seen")

    async def test_semaphore_limits_concurrency(self, mock_brotr: Brotr) -> None:
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        original_worker = Finder._find_from_events_worker

        async def _tracking_worker(
            self: Any, cursor: FinderCursor
        ) -> AsyncGenerator[tuple[dict[str, Any], str], None]:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            try:
                async for item in original_worker(self, cursor):
                    yield item
            finally:
                async with lock:
                    current_concurrent -= 1

        cursors = [FinderCursor(key=f"wss://relay{i}.com") for i in range(20)]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=cursors,
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                side_effect=lambda *_args: _mock_stream(),
            ),
            patch.object(Finder, "_find_from_events_worker", _tracking_worker),
        ):
            config = FinderConfig(
                events=EventsConfig(parallel_relays=3),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            assert max_concurrent <= 3

    async def test_unexpected_worker_error_logged_not_propagated(self, mock_brotr: Brotr) -> None:
        async def _failing_stream(
            brotr: Any,
            cursor: FinderCursor,
            batch_size: int,
        ) -> AsyncGenerator[dict[str, Any], None]:
            if cursor.key == "wss://bad.relay.com":
                raise RuntimeError("unexpected error")
            return
            yield  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_cursors_to_find",
                new_callable=AsyncMock,
                return_value=[
                    FinderCursor(key="wss://good.relay.com"),
                    FinderCursor(key="wss://bad.relay.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.stream_event_relays",
                side_effect=_failing_stream,
            ),
        ):
            finder = Finder(brotr=mock_brotr)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_gauge = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 0
            finder.set_gauge.assert_any_call("relays_seen", 0)


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
