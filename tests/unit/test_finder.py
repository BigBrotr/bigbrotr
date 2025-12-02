"""
Unit tests for services.finder module.

Tests:
- Configuration models (EventsConfig, ApiSourceConfig, ApiConfig, FinderConfig)
- Finder service initialization
- API fetching logic
- Error handling
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from core.brotr import Brotr
from services.finder import (
    ApiConfig,
    ApiSourceConfig,
    EventsConfig,
    Finder,
    FinderConfig,
)


# ============================================================================
# EventsConfig Tests
# ============================================================================


class TestEventsConfig:
    """Tests for EventsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default events configuration."""
        config = EventsConfig()
        assert config.enabled is True

    def test_disabled(self) -> None:
        """Test can disable events scanning."""
        config = EventsConfig(enabled=False)
        assert config.enabled is False


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


# ============================================================================
# FinderConfig Tests
# ============================================================================


class TestFinderConfig:
    """Tests for FinderConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = FinderConfig()

        assert config.interval == 3600.0
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
        assert finder._found_relays == 0

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


# ============================================================================
# Finder Run Tests
# ============================================================================


class TestFinderRun:
    """Tests for Finder.run() method."""

    @pytest.mark.asyncio
    async def test_run_all_disabled(self, mock_brotr: Brotr) -> None:
        """Test run with all discovery methods disabled."""
        config = FinderConfig(
            events=EventsConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        await finder.run()

        assert finder._found_relays == 0

    @pytest.mark.asyncio
    async def test_run_calls_both_methods(self, mock_brotr: Brotr) -> None:
        """Test run calls both discovery methods when enabled."""
        finder = Finder(brotr=mock_brotr)

        with patch.object(finder, "_find_from_events", new_callable=AsyncMock) as mock_events:
            with patch.object(finder, "_find_from_api", new_callable=AsyncMock) as mock_api:
                await finder.run()

                mock_events.assert_called_once()
                mock_api.assert_called_once()


# ============================================================================
# Finder API Fetching Tests
# ============================================================================


class TestFinderFindFromApi:
    """Tests for Finder._find_from_api() method."""

    @pytest.mark.asyncio
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

        await finder._find_from_api()

        assert finder._found_relays == 0

    @pytest.mark.asyncio
    async def test_find_from_api_success(self, mock_brotr: Brotr) -> None:
        """Test successful API fetch."""
        mock_brotr.insert_relays = AsyncMock(return_value=2)  # type: ignore[attr-defined]

        config = FinderConfig(
            api=ApiConfig(
                enabled=True,
                sources=[ApiSourceConfig(url="https://api.example.com")],
                delay_between_requests=0,
            )
        )
        finder = Finder(brotr=mock_brotr, config=config)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=["wss://relay1.com", "wss://relay2.com"])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            await finder._find_from_api()

            assert finder._found_relays == 2

    @pytest.mark.asyncio
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

            # Should not raise
            await finder._find_from_api()

            assert finder._found_relays == 0


# ============================================================================
# Finder Single API Fetch Tests
# ============================================================================


class TestFinderFetchSingleApi:
    """Tests for Finder._fetch_single_api() method."""

    @pytest.mark.asyncio
    async def test_fetch_single_api_valid_relays(self, mock_brotr: Brotr) -> None:
        """Test fetching valid relay URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=["wss://relay1.com", "wss://relay2.com"])
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 2
        assert "wss://relay1.com" in result
        assert "wss://relay2.com" in result

    @pytest.mark.asyncio
    async def test_fetch_single_api_filters_invalid_urls(self, mock_brotr: Brotr) -> None:
        """Test fetching filters out invalid relay URLs."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value=["wss://valid.relay.com", "invalid-url", "not-a-relay"]
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 1
        assert "wss://valid.relay.com" in result

    @pytest.mark.asyncio
    async def test_fetch_single_api_handles_non_list_response(self, mock_brotr: Brotr) -> None:
        """Test fetching handles non-list API response."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value={"relays": ["wss://relay.com"]})  # Dict, not list
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0  # No relays extracted from dict response

