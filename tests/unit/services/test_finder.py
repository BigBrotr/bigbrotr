"""
Unit tests for services.finder module.

Tests:
- Configuration models (EventsConfig, ApiSourceConfig, ApiConfig, FinderConfig)
- Finder service initialization
- API fetching logic
- Event scanning logic
- Cursor persistence
- Error handling
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.common.utils import validate_relay_url
from bigbrotr.services.finder import (
    ApiConfig,
    ApiSourceConfig,
    EventsConfig,
    Finder,
    FinderConcurrencyConfig,
    FinderConfig,
)


def _mock_api_response(data: Any) -> MagicMock:
    """Build a mock aiohttp response returning *data* as bounded JSON body."""
    body = json.dumps(data).encode()
    content = MagicMock()
    content.read = AsyncMock(return_value=body)

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


# ============================================================================
# FinderConcurrencyConfig Tests
# ============================================================================


class TestFinderConcurrencyConfig:
    """Tests for FinderConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency configuration."""
        config = FinderConcurrencyConfig()
        assert config.max_parallel == 5

    def test_custom_values(self) -> None:
        """Test custom concurrency configuration."""
        config = FinderConcurrencyConfig(max_parallel=10)
        assert config.max_parallel == 10

    def test_max_parallel_bounds(self) -> None:
        """Test max_parallel validation bounds."""
        # Min bound
        config_min = FinderConcurrencyConfig(max_parallel=1)
        assert config_min.max_parallel == 1

        # Max bound
        config_max = FinderConcurrencyConfig(max_parallel=20)
        assert config_max.max_parallel == 20

        # Below min
        with pytest.raises(ValueError):
            FinderConcurrencyConfig(max_parallel=0)

        # Above max
        with pytest.raises(ValueError):
            FinderConcurrencyConfig(max_parallel=21)


# ============================================================================
# EventsConfig Tests
# ============================================================================


class TestEventsConfig:
    """Tests for EventsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default events configuration."""
        config = EventsConfig()
        assert config.enabled is True
        assert config.batch_size == 1000
        assert config.kinds == [3, 10002]

    def test_disabled(self) -> None:
        """Test can disable events scanning."""
        config = EventsConfig(enabled=False)
        assert config.enabled is False

    def test_custom_kinds(self) -> None:
        """Test custom event kinds."""
        config = EventsConfig(kinds=[30303])
        assert config.kinds == [30303]

    def test_batch_size_bounds(self) -> None:
        """Test batch_size validation bounds."""
        # Min bound
        config_min = EventsConfig(batch_size=100)
        assert config_min.batch_size == 100

        # Max bound
        config_max = EventsConfig(batch_size=10000)
        assert config_max.batch_size == 10000

        # Below min
        with pytest.raises(ValueError):
            EventsConfig(batch_size=50)

        # Above max
        with pytest.raises(ValueError):
            EventsConfig(batch_size=20000)


# ============================================================================
# ApiSourceConfig Tests
# ============================================================================


class TestApiSourceConfig:
    """Tests for ApiSourceConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default API source configuration."""
        config = ApiSourceConfig(url="https://api.example.com")

        assert config.url == "https://api.example.com"
        assert config.enabled is True
        assert config.timeout == 30.0

    def test_custom_values(self) -> None:
        """Test custom API source configuration."""
        config = ApiSourceConfig(
            url="https://custom.api.com",
            enabled=False,
            timeout=60.0,
        )

        assert config.url == "https://custom.api.com"
        assert config.enabled is False
        assert config.timeout == 60.0

    def test_timeout_bounds(self) -> None:
        """Test timeout validation bounds."""
        # Min bound
        config_min = ApiSourceConfig(url="https://api.com", timeout=0.1)
        assert config_min.timeout == 0.1

        # Max bound
        config_max = ApiSourceConfig(url="https://api.com", timeout=120.0)
        assert config_max.timeout == 120.0


# ============================================================================
# ApiConfig Tests
# ============================================================================


class TestApiConfig:
    """Tests for ApiConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default API configuration."""
        config = ApiConfig()

        assert config.enabled is True
        assert len(config.sources) == 2
        assert config.delay_between_requests == 1.0
        assert config.verify_ssl is True

    def test_default_sources(self) -> None:
        """Test default API sources include nostr.watch."""
        config = ApiConfig()

        urls = [s.url for s in config.sources]
        assert "https://api.nostr.watch/v1/online" in urls
        assert "https://api.nostr.watch/v1/offline" in urls

    def test_custom_sources(self) -> None:
        """Test custom API sources."""
        config = ApiConfig(
            sources=[
                ApiSourceConfig(url="https://custom1.api.com"),
                ApiSourceConfig(url="https://custom2.api.com"),
            ]
        )

        assert len(config.sources) == 2
        assert config.sources[0].url == "https://custom1.api.com"

    def test_verify_ssl_disabled(self) -> None:
        """Test SSL verification can be disabled."""
        config = ApiConfig(verify_ssl=False)
        assert config.verify_ssl is False

    def test_max_response_size_default(self) -> None:
        """Test default max_response_size is 5 MB."""
        config = ApiConfig()
        assert config.max_response_size == 5_242_880

    def test_max_response_size_custom(self) -> None:
        """Test custom max_response_size."""
        config = ApiConfig(max_response_size=1_048_576)
        assert config.max_response_size == 1_048_576

    def test_max_response_size_bounds(self) -> None:
        """Test max_response_size validation bounds."""
        with pytest.raises(ValueError):
            ApiConfig(max_response_size=512)  # Below min (1024)

        with pytest.raises(ValueError):
            ApiConfig(max_response_size=100_000_000)  # Above max (50 MB)


# ============================================================================
# FinderConfig Tests
# ============================================================================


class TestFinderConfig:
    """Tests for FinderConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration (inherits from BaseServiceConfig)."""
        config = FinderConfig()

        assert config.interval == 300.0  # BaseServiceConfig default
        assert config.max_consecutive_failures == 5  # BaseServiceConfig default
        assert config.events.enabled is True
        assert config.api.enabled is True

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = FinderConfig(
            interval=7200.0,
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )

        assert config.interval == 7200.0
        assert config.events.enabled is False
        assert config.api.enabled is False

    def test_concurrency_config(self) -> None:
        """Test concurrency configuration."""
        config = FinderConfig(concurrency=FinderConcurrencyConfig(max_parallel=15))
        assert config.concurrency.max_parallel == 15


# ============================================================================
# Finder Initialization Tests
# ============================================================================


class TestFinderInit:
    """Tests for Finder initialization."""

    def test_init_with_defaults(self, mock_brotr: Brotr) -> None:
        """Test initialization with default config."""
        finder = Finder(brotr=mock_brotr)

        assert finder._brotr is mock_brotr
        assert finder.SERVICE_NAME == "finder"
        assert finder.config.api.enabled is True

    def test_init_with_custom_config(self, mock_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = FinderConfig(
            api=ApiConfig(enabled=False),
            events=EventsConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        assert finder.config.api.enabled is False
        assert finder.config.events.enabled is False

    def test_from_dict(self, mock_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "interval": 1800.0,
            "api": {"enabled": False},
            "events": {"enabled": False},
        }
        finder = Finder.from_dict(data, brotr=mock_brotr)

        assert finder.config.interval == 1800.0
        assert finder.config.api.enabled is False

    def test_service_name_class_attribute(self, mock_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        assert Finder.SERVICE_NAME == "finder"

    def test_config_class_attribute(self, mock_brotr: Brotr) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert FinderConfig == Finder.CONFIG_CLASS


# ============================================================================
# Finder Run Tests
# ============================================================================


class TestFinderRun:
    """Tests for Finder.run() method."""

    async def test_run_all_disabled(self, mock_brotr: Brotr) -> None:
        """Test run with all discovery methods disabled."""
        config = FinderConfig(
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        await finder.run()

    async def test_run_calls_both_methods(self, mock_brotr: Brotr) -> None:
        """Test run calls both discovery methods when enabled."""
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


# ============================================================================
# Finder API Fetching Tests
# ============================================================================


class TestFinderFindFromApi:
    """Tests for Finder.find_from_api() method."""

    async def test_find_from_api_all_sources_disabled(self, mock_brotr: Brotr) -> None:
        """Test API fetch when all sources are disabled."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[
                    ApiSourceConfig(url="https://api.example.com", enabled=False),
                ],
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)

        result = await finder.find_from_api()

        assert result == 0

    async def test_find_from_api_success(self, mock_brotr: Brotr) -> None:
        """Test successful API fetch."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                delay_between_requests=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)

        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])

        with (
            patch("aiohttp.ClientSession") as mock_session_cls,
            patch(
                "bigbrotr.services.finder.service.insert_candidates",
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

    async def test_find_from_api_handles_errors(self, mock_brotr: Brotr) -> None:
        """Test API fetch handles errors gracefully."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                delay_between_requests=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection failed"))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            result = await finder.find_from_api()

            assert result == 0


# ============================================================================
# Finder Single API Fetch Tests
# ============================================================================


class TestFinderFetchSingleApi:
    """Tests for Finder._fetch_single_api() method."""

    async def test_fetch_single_api_valid_relays(self, mock_brotr: Brotr) -> None:
        """Test fetching valid relay URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response(["wss://relay1.com", "wss://relay2.com"])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [str(r) for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_filters_invalid_urls(self, mock_brotr: Brotr) -> None:
        """Test fetching filters out invalid relay URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response(["wss://valid.relay.com", "invalid-url", "not-a-relay"])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 1
        result_urls = [str(r) for r in result]
        assert "wss://valid.relay.com" in result_urls

    async def test_fetch_single_api_handles_non_list_response(self, mock_brotr: Brotr) -> None:
        """Test fetching handles non-list API response."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response({"relays": ["wss://relay.com"]})
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0  # No relays extracted from dict response

    async def test_fetch_single_api_handles_empty_list(self, mock_brotr: Brotr) -> None:
        """Test fetching handles empty list response."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = _mock_api_response([])
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0

    async def test_fetch_single_api_rejects_oversized_response(self, mock_brotr: Brotr) -> None:
        """Oversized API response raises ValueError (caught by find_from_api)."""
        config = FinderConfig(api=ApiConfig(max_response_size=1024))
        finder = Finder(brotr=mock_brotr, config=config)
        source = ApiSourceConfig(url="https://api.example.com")

        # Body larger than max_response_size (1024 bytes)
        oversized_body = b"x" * 1025
        content = MagicMock()
        content.read = AsyncMock(return_value=oversized_body)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.content = content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(ValueError, match="Response body too large"):
            await finder._fetch_single_api(mock_session, source)


# ============================================================================
# find_from_events() Tests
# ============================================================================


class TestFinderFindFromEvents:
    """Tests for Finder.find_from_events() method."""

    async def test_empty_database_returns_no_urls(self, mock_brotr: Brotr) -> None:
        """Empty database (no relays) returns no URLs."""
        mock_brotr._pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        result = await finder.find_from_events()

        assert result == 0

    async def test_valid_relay_urls_extracted_from_kind_2(self, mock_brotr: Brotr) -> None:
        """Valid relay URLs extracted from kind 2 events."""
        mock_event = {
            "id": b"\x01" * 32,
            "created_at": 1700000000,
            "kind": 2,
            "tags": None,
            "content": "wss://relay.example.com",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
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

    async def test_valid_relay_urls_extracted_from_kind_10002(self, mock_brotr: Brotr) -> None:
        """Valid relay URLs extracted from kind 10002 events."""
        mock_event = {
            "id": b"\x02" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [["r", "wss://relay1.example.com"], ["r", "wss://relay2.example.com"]],
            "content": "",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
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

    async def test_urls_extracted_from_r_tags(self, mock_brotr: Brotr) -> None:
        """URLs extracted from r tags in event content."""
        mock_event = {
            "id": b"\x04" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [["r", "wss://rtag-relay.com"], ["e", "someid"]],
            "content": "",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
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
        """Invalid/malformed URLs filtered out."""
        mock_event = {
            "id": b"\x05" * 32,
            "created_at": 1700000000,
            "kind": 2,
            "tags": [["r", "not-a-valid-url"], ["r", "http://wrong-scheme.com"]],
            "content": "also-not-valid",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 0

            mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            result = await finder.find_from_events()

            assert result == 0

    async def test_duplicate_urls_deduplicated(self, mock_brotr: Brotr) -> None:
        """Duplicate URLs deduplicated."""
        mock_event = {
            "id": b"\x06" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [
                ["r", "wss://duplicate.relay.com"],
                ["r", "wss://duplicate.relay.com"],
                ["r", "wss://duplicate.relay.com"],
            ],
            "content": "",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
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
        """Cursor position updated after scan."""
        mock_event = {
            "id": b"\x07" * 32,
            "created_at": 1700000100,
            "kind": 2,
            "tags": None,
            "content": "wss://relay.example.com",
            "seen_at": 1700000200,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
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
        """Exception handling during database query."""
        mock_brotr._pool.fetch = AsyncMock(side_effect=OSError("Database connection error"))  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        result = await finder.find_from_events()

        assert result == 0

    async def test_network_type_detected_clearnet_vs_tor(self, mock_brotr: Brotr) -> None:
        """Network type correctly detected (clearnet vs tor)."""
        mock_event = {
            "id": b"\x08" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [
                ["r", "wss://clearnet.relay.com"],
                ["r", "ws://tortest.onion"],
            ],
            "content": "",
            "seen_at": 1700000001,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.get_all_relay_urls", new_callable=AsyncMock
            ) as mock_get_relay_urls,
            patch(
                "bigbrotr.services.finder.service.get_all_service_cursors",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.get_events_with_relay_urls",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relay_urls.return_value = ["wss://source.relay.com"]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 2

            mock_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()


# ============================================================================
# Validate Relay URL Tests
# ============================================================================


class TestValidateRelayUrl:
    """Tests for validate_relay_url() utility function."""

    def test_validate_valid_wss_url(self) -> None:
        """Test validating valid wss:// URL."""
        result = validate_relay_url("wss://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_validate_valid_ws_url(self) -> None:
        """Clearnet ws:// URL is automatically upgraded to wss://."""
        result = validate_relay_url("ws://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_validate_invalid_url(self) -> None:
        """Test validating invalid URL returns None."""
        assert validate_relay_url("not-a-url") is None
        assert validate_relay_url("http://wrong-scheme.com") is None
        assert validate_relay_url("") is None
        assert validate_relay_url(None) is None  # type: ignore[arg-type]

    def test_validate_tor_url(self) -> None:
        """Test validating Tor .onion URL."""
        result = validate_relay_url("ws://example.onion")

        assert result is not None
        assert "onion" in result.url

    def test_validate_i2p_url(self) -> None:
        """Test validating I2P .i2p URL."""
        result = validate_relay_url("ws://example.i2p")

        assert result is not None
        assert "i2p" in result.url

    def test_validate_strips_whitespace(self) -> None:
        """Test validating strips whitespace."""
        result = validate_relay_url("  wss://relay.example.com  ")

        assert result is not None
        assert result.url == "wss://relay.example.com"
