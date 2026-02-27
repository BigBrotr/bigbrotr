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
import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.services.common.types import EventRelayCursor
from bigbrotr.services.common.utils import parse_relay_url
from bigbrotr.services.finder import (
    ApiConfig,
    ApiSourceConfig,
    ConcurrencyConfig,
    EventsConfig,
    Finder,
    FinderConfig,
)


def _mock_api_response(data: Any) -> MagicMock:
    """Build a mock aiohttp response returning *data* as bounded JSON body."""
    body = json.dumps(data).encode()
    content = MagicMock()
    content.read = AsyncMock(side_effect=[body, b""])

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency configuration."""
        config = ConcurrencyConfig()
        assert config.max_parallel_events == 10

    def test_custom_values(self) -> None:
        """Test custom concurrency configuration."""
        config = ConcurrencyConfig(max_parallel_events=20)
        assert config.max_parallel_events == 20

    def test_max_parallel_events_bounds(self) -> None:
        """Test max_parallel_events validation bounds."""
        config_min = ConcurrencyConfig(max_parallel_events=1)
        assert config_min.max_parallel_events == 1

        config_max = ConcurrencyConfig(max_parallel_events=50)
        assert config_max.max_parallel_events == 50

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel_events=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel_events=51)


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

    def test_disabled(self) -> None:
        """Test can disable events scanning."""
        config = EventsConfig(enabled=False)
        assert config.enabled is False

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
        assert config.jmespath == "[*]"

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

    def test_custom_jmespath_expression(self) -> None:
        config = ApiSourceConfig(
            url="https://api.example.com",
            jmespath="data.relays[*].url",
        )
        assert config.jmespath == "data.relays[*].url"

    def test_invalid_jmespath_expression_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid JMESPath expression"):
            ApiSourceConfig(
                url="https://api.example.com",
                jmespath="[*",
            )


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
        config = FinderConfig(concurrency=ConcurrencyConfig(max_parallel_events=15))
        assert config.concurrency.max_parallel_events == 15


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
        """Default [*] expression on a dict response yields nothing."""
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
        """Oversized API response raises ValueError (caught by find_from_api)."""
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
        """JMESPath navigates into a nested dict before extracting URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            jmespath="data.relays",
        )

        mock_response = _mock_api_response(
            {"data": {"relays": ["wss://relay1.com", "wss://relay2.com"]}}
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [str(r) for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_with_field_extraction(self, mock_brotr: Brotr) -> None:
        """JMESPath [*].field extracts URLs from list-of-dicts responses."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            jmespath="[*].address",
        )

        mock_response = _mock_api_response(
            [{"address": "wss://relay1.com"}, {"address": "wss://relay2.com"}]
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [str(r) for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

    async def test_fetch_single_api_with_keys_extraction(self, mock_brotr: Brotr) -> None:
        """JMESPath keys(@) extracts dict keys as relay URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(
            url="https://api.example.com",
            jmespath="keys(@)",
        )

        mock_response = _mock_api_response(
            {"wss://relay1.com": {"uptime": 0.99}, "wss://relay2.com": {}}
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        result_urls = [str(r) for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls


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

    async def test_valid_relay_urls_extracted_from_tagvalues(self, mock_brotr: Brotr) -> None:
        """Valid relay URLs extracted from event tagvalues."""
        mock_event = {
            "tagvalues": ["wss://relay.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
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
        """Multiple relay URLs extracted from event tagvalues."""
        mock_event = {
            "tagvalues": ["wss://relay1.example.com", "wss://relay2.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
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
        """Non-URL tagvalues (hex IDs, hashtags) are filtered out."""
        mock_event = {
            "tagvalues": ["wss://rtag-relay.com", "a" * 64, "bitcoin"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
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
            "tagvalues": ["not-a-valid-url", "http://wrong-scheme.com", "also-not-valid"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 0

            mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            result = await finder.find_from_events()

            assert result == 0

    async def test_duplicate_urls_deduplicated(self, mock_brotr: Brotr) -> None:
        """Duplicate URLs deduplicated."""
        mock_event = {
            "tagvalues": [
                "wss://duplicate.relay.com",
                "wss://duplicate.relay.com",
                "wss://duplicate.relay.com",
            ],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
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
            "tagvalues": ["wss://relay.example.com"],
            "seen_at": 1700000200,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
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
            "tagvalues": ["wss://clearnet.relay.com", "ws://tortest.onion"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays", new_callable=AsyncMock
            ) as mock_get_relays,
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
            ) as mock_get_events,
            patch(
                "bigbrotr.services.finder.service.insert_candidates", new_callable=AsyncMock
            ) as mock_insert,
        ):
            mock_get_relays.return_value = [Relay("wss://source.relay.com")]
            mock_get_events.side_effect = [[mock_event], []]
            mock_insert.return_value = 2

            mock_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            mock_insert.assert_called()


# ============================================================================
# Finder Event Scanning Concurrency Tests
# ============================================================================


class TestFinderEventScanConcurrency:
    """Tests for concurrent event scanning in find_from_events()."""

    async def test_multiple_relays_scanned_concurrently(self, mock_brotr: Brotr) -> None:
        """Multiple relays are scanned via TaskGroup, not sequentially."""
        mock_event = {
            "tagvalues": ["wss://found.relay.com"],
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
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=[
                    Relay("wss://relay1.com"),
                    Relay("wss://relay2.com"),
                    Relay("wss://relay3.com"),
                ],
            ),
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=_events_side_effect,
            ),
            patch(
                "bigbrotr.services.finder.service.insert_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            config = FinderConfig(
                concurrency=ConcurrencyConfig(max_parallel_events=10),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            result = await finder.find_from_events()

            assert result == 3
            finder.set_gauge.assert_any_call("relays_processed", 3)

    async def test_task_failure_does_not_block_others(self, mock_brotr: Brotr) -> None:
        """A DB error in one relay scan does not prevent other relays from completing."""
        mock_event = {
            "tagvalues": ["wss://found.relay.com"],
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
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=[Relay("wss://good.relay.com"), Relay("wss://failing.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=_events_side_effect,
            ),
            patch(
                "bigbrotr.services.finder.service.insert_candidates",
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
            finder.set_gauge.assert_any_call("relays_processed", 2)

    async def test_semaphore_limits_concurrency(self, mock_brotr: Brotr) -> None:
        """Semaphore limits the number of concurrent scans."""
        import asyncio

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        original_scan = Finder._scan_relay_events

        async def _tracking_scan(
            self: Any, relay_url: str, cursors: dict[str, EventRelayCursor]
        ) -> tuple[int, int]:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            try:
                return await original_scan(self, relay_url, cursors)
            finally:
                async with lock:
                    current_concurrent -= 1

        relays = [Relay(f"wss://relay{i}.com") for i in range(20)]

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=relays,
            ),
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(Finder, "_scan_relay_events", _tracking_scan),
        ):
            config = FinderConfig(
                concurrency=ConcurrencyConfig(max_parallel_events=3),
            )
            finder = Finder(brotr=mock_brotr, config=config)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            assert max_concurrent <= 3


# ============================================================================
# Parse Relay URL Tests
# ============================================================================


class TestParseRelayUrl:
    """Tests for parse_relay_url() utility function."""

    def test_parse_valid_wss_url(self) -> None:
        """Test parsing valid wss:// URL."""
        result = parse_relay_url("wss://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_parse_valid_ws_url(self) -> None:
        """Clearnet ws:// URL is automatically upgraded to wss://."""
        result = parse_relay_url("ws://relay.example.com")

        assert result is not None
        assert result.url == "wss://relay.example.com"

    def test_parse_invalid_url(self) -> None:
        """Test parsing invalid URL returns None."""
        assert parse_relay_url("not-a-url") is None
        assert parse_relay_url("http://wrong-scheme.com") is None
        assert parse_relay_url("") is None
        assert parse_relay_url(None) is None  # type: ignore[arg-type]

    def test_parse_tor_url(self) -> None:
        """Test parsing Tor .onion URL."""
        result = parse_relay_url("ws://example.onion")

        assert result is not None
        assert "onion" in result.url

    def test_parse_i2p_url(self) -> None:
        """Test parsing I2P .i2p URL."""
        result = parse_relay_url("ws://example.i2p")

        assert result is not None
        assert "i2p" in result.url

    def test_parse_strips_whitespace(self) -> None:
        """Test parsing strips whitespace."""
        result = parse_relay_url("  wss://relay.example.com  ")

        assert result is not None
        assert result.url == "wss://relay.example.com"


# ============================================================================
# Finder Metrics Tests
# ============================================================================


class TestFinderMetrics:
    """Tests for Finder Prometheus metric emission."""

    async def test_find_from_events_emits_gauges_and_counters(self, mock_brotr: Brotr) -> None:
        """Test find_from_events emits gauges and counters for scanned events."""
        mock_event = {
            "tagvalues": ["wss://relay1.example.com", "wss://relay2.example.com"],
            "seen_at": 1700000001,
            "event_id": b"\xab" * 32,
        }

        with (
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=[Relay("wss://source.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "bigbrotr.services.finder.service.scan_event_relay",
                new_callable=AsyncMock,
                side_effect=[[mock_event], []],
            ),
            patch(
                "bigbrotr.services.finder.service.insert_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

            finder = Finder(brotr=mock_brotr)
            finder.set_gauge = MagicMock()  # type: ignore[method-assign]
            finder.inc_counter = MagicMock()  # type: ignore[method-assign]

            await finder.find_from_events()

            finder.set_gauge.assert_any_call("events_scanned", 1)
            finder.set_gauge.assert_any_call("relays_found", 2)
            finder.set_gauge.assert_any_call("relays_processed", 1)
            finder.inc_counter.assert_any_call("total_events_scanned", 1)
            finder.inc_counter.assert_any_call("total_relays_found", 2)

    async def test_find_from_events_disabled_no_metrics(self, mock_brotr: Brotr) -> None:
        """Test find_from_events emits no metrics when events disabled."""
        config = FinderConfig(events=EventsConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_counter = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_events()

        assert result == 0
        finder.set_gauge.assert_not_called()
        finder.inc_counter.assert_not_called()

    async def test_find_from_api_emits_gauge(self, mock_brotr: Brotr) -> None:
        """Test find_from_api emits api_relays gauge."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                delay_between_requests=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]

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

            await finder.find_from_api()

            finder.set_gauge.assert_any_call("api_relays", 2)

    async def test_find_from_api_disabled_no_metrics(self, mock_brotr: Brotr) -> None:
        """Test find_from_api emits no metrics when API disabled."""
        config = FinderConfig(api=ApiConfig(enabled=False))
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]

        result = await finder.find_from_api()

        assert result == 0
        finder.set_gauge.assert_not_called()

    async def test_find_from_api_emits_counter(self, mock_brotr: Brotr) -> None:
        """Test find_from_api emits total_api_relays_found counter."""
        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                delay_between_requests=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)
        finder.set_gauge = MagicMock()  # type: ignore[method-assign]
        finder.inc_counter = MagicMock()  # type: ignore[method-assign]

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

            await finder.find_from_api()

            finder.inc_counter.assert_any_call("total_api_relays_found", 2)

    async def test_find_from_events_emits_relays_failed_gauge(self, mock_brotr: Brotr) -> None:
        """Test find_from_events emits relays_failed gauge when tasks fail."""

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
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=[Relay("wss://good.relay.com"), Relay("wss://bad.relay.com")],
            ),
            patch(
                "bigbrotr.services.finder.service.get_all_cursor_values",
                new_callable=AsyncMock,
                return_value={},
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

            finder.set_gauge.assert_any_call("relays_failed", 1)
            finder.set_gauge.assert_any_call("relays_processed", 1)


# ============================================================================
# Finder _persist_scan_chunk Tests
# ============================================================================


class TestFinderPersistScanChunk:
    """Tests for Finder._persist_scan_chunk() cursor error handling."""

    async def test_cursor_update_failure_does_not_propagate(self, mock_brotr: Brotr) -> None:
        """Cursor update failure is logged but does not raise."""
        mock_brotr.upsert_service_state = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("cursor flush failed")
        )

        with patch(
            "bigbrotr.services.finder.service.insert_candidates",
            new_callable=AsyncMock,
            return_value=1,
        ):
            finder = Finder(brotr=mock_brotr)
            relays = {
                "wss://found.relay.com": MagicMock(url="wss://found.relay.com"),
            }

            # Should NOT raise despite cursor update failure
            cursor = EventRelayCursor(
                relay_url="wss://source.relay.com",
                seen_at=1700000001,
                event_id=b"\xab" * 32,
            )
            result = await finder._persist_scan_chunk(relays, cursor)

            assert result == 1

    async def test_cursor_update_failure_with_empty_relays(self, mock_brotr: Brotr) -> None:
        """Cursor update failure with no relays still does not raise."""
        mock_brotr.upsert_service_state = AsyncMock(  # type: ignore[method-assign]
            side_effect=OSError("connection lost")
        )

        finder = Finder(brotr=mock_brotr)

        # Should NOT raise
        cursor = EventRelayCursor(
            relay_url="wss://source.relay.com",
            seen_at=1700000001,
            event_id=b"\xab" * 32,
        )
        result = await finder._persist_scan_chunk({}, cursor)

        assert result == 0


# ============================================================================
# Finder Orphan Cursor Cleanup Tests
# ============================================================================


class TestFinderOrphanCursorCleanup:
    """Tests for orphan cursor cleanup in find_from_events()."""

    async def test_orphan_cursors_cleaned_before_scan(self, mock_brotr: Brotr) -> None:
        """delete_orphan_cursors is called before relay fetch."""
        call_order: list[str] = []

        async def _mock_delete_orphan(*args: Any, **kwargs: Any) -> int:
            call_order.append("delete_orphan_cursors")
            return 3

        async def _mock_get_relays(*args: Any, **kwargs: Any) -> list[Relay]:
            call_order.append("fetch_all_relays")
            return []

        with (
            patch(
                "bigbrotr.services.finder.service.delete_orphan_cursors",
                new_callable=AsyncMock,
                side_effect=_mock_delete_orphan,
            ),
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                side_effect=_mock_get_relays,
            ),
        ):
            finder = Finder(brotr=mock_brotr)
            await finder.find_from_events()

            assert call_order == ["delete_orphan_cursors", "fetch_all_relays"]

    async def test_orphan_cursor_cleanup_failure_does_not_block(self, mock_brotr: Brotr) -> None:
        """Orphan cursor cleanup DB error does not prevent event scanning."""
        with (
            patch(
                "bigbrotr.services.finder.service.delete_orphan_cursors",
                new_callable=AsyncMock,
                side_effect=asyncpg.PostgresError("cleanup failed"),
            ),
            patch(
                "bigbrotr.services.finder.service.fetch_all_relays",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_get_relays,
        ):
            finder = Finder(brotr=mock_brotr)
            result = await finder.find_from_events()

            assert result == 0
            mock_get_relays.assert_awaited_once()


class TestFinderFetchAllCursors:
    """Tests for Finder._fetch_all_cursors() cursor parsing and validation."""

    async def test_invalid_event_id_hex_skipped_with_warning(self, mock_brotr: Brotr) -> None:
        """Non-hex event_id is skipped and a warning is logged."""
        with patch(
            "bigbrotr.services.finder.service.get_all_cursor_values",
            new_callable=AsyncMock,
            return_value={
                "wss://good.com": {"seen_at": 100, "event_id": "ab" * 32},
                "wss://bad.com": {"seen_at": 200, "event_id": "not-hex"},
            },
        ):
            finder = Finder(brotr=mock_brotr)
            cursors = await finder._fetch_all_cursors()

        assert "wss://good.com" in cursors
        assert "wss://bad.com" not in cursors

    async def test_invalid_seen_at_skipped_with_warning(self, mock_brotr: Brotr) -> None:
        """Non-integer seen_at is skipped and a warning is logged."""
        with patch(
            "bigbrotr.services.finder.service.get_all_cursor_values",
            new_callable=AsyncMock,
            return_value={
                "wss://good.com": {"seen_at": 100, "event_id": "cd" * 32},
                "wss://bad.com": {"seen_at": "not-a-number", "event_id": "ab" * 32},
            },
        ):
            finder = Finder(brotr=mock_brotr)
            cursors = await finder._fetch_all_cursors()

        assert "wss://good.com" in cursors
        assert cursors["wss://good.com"] == EventRelayCursor(
            relay_url="wss://good.com",
            seen_at=100,
            event_id=bytes.fromhex("cd" * 32),
        )
        assert "wss://bad.com" not in cursors
