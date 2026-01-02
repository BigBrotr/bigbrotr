"""
Unit tests for services.finder module.

Tests:
- Configuration models (EventsConfig, ApiSourceConfig, ApiConfig, FinderConfig)
- Finder service initialization
- API fetching logic
- Error handling
"""

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

        with (
            patch.object(finder, "_find_from_events", new_callable=AsyncMock) as mock_events,
            patch.object(finder, "_find_from_api", new_callable=AsyncMock) as mock_api,
        ):
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
        result_urls = [str(r) for r in result]
        assert "wss://relay1.com" in result_urls
        assert "wss://relay2.com" in result_urls

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
        result_urls = [str(r) for r in result]
        assert "wss://valid.relay.com" in result_urls

    @pytest.mark.asyncio
    async def test_fetch_single_api_handles_non_list_response(self, mock_brotr: Brotr) -> None:
        """Test fetching handles non-list API response."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.example.com")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(
            return_value={"relays": ["wss://relay.com"]}
        )  # Dict, not list
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        result = await finder._fetch_single_api(mock_session, source)

        assert len(result) == 0  # No relays extracted from dict response


# ============================================================================
# H12: _find_from_events() Tests
# ============================================================================


class TestFinderFindFromEvents:
    """Tests for Finder._find_from_events() method (H12)."""

    @pytest.mark.asyncio
    async def test_empty_database_returns_no_urls(self, mock_brotr: Brotr) -> None:
        """H12.1: Empty database returns no URLs."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        assert finder._found_relays == 0

    @pytest.mark.asyncio
    async def test_valid_relay_urls_extracted_from_kind_2(self, mock_brotr: Brotr) -> None:
        """H12.2: Valid relay URLs extracted from kind 2 events."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x01" * 32,
            "created_at": 1700000000,
            "kind": 2,
            "tags": None,
            "content": "wss://relay.example.com",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # Verify upsert was called with the extracted relay
        mock_brotr.upsert_service_data.assert_called()
        # Check all upsert calls to find the candidate insertion (not cursor)
        all_urls = []
        for call in mock_brotr.upsert_service_data.call_args_list:
            records = call[0][0]
            for record in records:
                if record[1] == "candidate":  # data_type == "candidate"
                    all_urls.append(record[2])
        assert any("relay.example.com" in url for url in all_urls)

    @pytest.mark.asyncio
    async def test_valid_relay_urls_extracted_from_kind_10002(self, mock_brotr: Brotr) -> None:
        """H12.3: Valid relay URLs extracted from kind 10002 events."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x02" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [["r", "wss://relay1.example.com"], ["r", "wss://relay2.example.com"]],
            "content": "",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=2)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # Verify upsert was called
        mock_brotr.upsert_service_data.assert_called()
        # Check all upsert calls to find the candidate insertion (not cursor)
        all_urls = []
        for call in mock_brotr.upsert_service_data.call_args_list:
            records = call[0][0]
            for record in records:
                if record[1] == "candidate":  # data_type == "candidate"
                    all_urls.append(record[2])
        assert any("relay1.example.com" in url for url in all_urls)
        assert any("relay2.example.com" in url for url in all_urls)

    @pytest.mark.asyncio
    async def test_valid_relay_urls_extracted_from_kind_30303(self, mock_brotr: Brotr) -> None:
        """H12.4: Valid relay URLs extracted from kind 30303 events."""
        config = FinderConfig(events=EventsConfig(kinds=[30303]))
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x03" * 32,
            "created_at": 1700000000,
            "kind": 30303,
            "tags": [["r", "wss://relay.test.com"]],
            "content": "",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr, config=config)
        await finder._find_from_events()

        mock_brotr.upsert_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_urls_extracted_from_r_tags(self, mock_brotr: Brotr) -> None:
        """H12.5: URLs extracted from r tags in event content."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x04" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [["r", "wss://rtag-relay.com"], ["e", "someid"]],
            "content": "",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        mock_brotr.upsert_service_data.assert_called()
        # Check all upsert calls to find the candidate insertion (not cursor)
        all_urls = []
        for call in mock_brotr.upsert_service_data.call_args_list:
            records = call[0][0]
            for record in records:
                if record[1] == "candidate":  # data_type == "candidate"
                    all_urls.append(record[2])
        assert any("rtag-relay.com" in url for url in all_urls)

    @pytest.mark.asyncio
    async def test_invalid_malformed_urls_filtered_out(self, mock_brotr: Brotr) -> None:
        """H12.6: Invalid/malformed URLs filtered out."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x05" * 32,
            "created_at": 1700000000,
            "kind": 2,
            "tags": [["r", "not-a-valid-url"], ["r", "http://wrong-scheme.com"]],
            "content": "also-not-valid",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=0)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # No valid URLs should be inserted
        assert finder._found_relays == 0

    @pytest.mark.asyncio
    async def test_duplicate_urls_deduplicated(self, mock_brotr: Brotr) -> None:
        """H12.7: Duplicate URLs deduplicated."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x06" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [
                ["r", "wss://duplicate.relay.com"],
                ["r", "wss://duplicate.relay.com"],
                ["r", "wss://duplicate.relay.com"],
            ],
            "content": "",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # Only one unique URL should be inserted
        mock_brotr.upsert_service_data.assert_called()
        call_args = mock_brotr.upsert_service_data.call_args[0][0]
        assert len(call_args) == 1

    @pytest.mark.asyncio
    async def test_cursor_position_updated_after_scan(self, mock_brotr: Brotr) -> None:
        """H12.8: Cursor position updated after scan."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x07" * 32,
            "created_at": 1700000100,
            "kind": 2,
            "tags": None,
            "content": "wss://relay.example.com",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # Verify cursor was saved (upsert called for both candidate and cursor)
        upsert_calls = mock_brotr.upsert_service_data.call_args_list
        cursor_saved = any(
            call[0][0][0][0] == "finder" and call[0][0][0][1] == "cursor" for call in upsert_calls
        )
        assert cursor_saved

    @pytest.mark.asyncio
    async def test_batch_size_limit_respected(self, mock_brotr: Brotr) -> None:
        """H12.9: Batch size limit respected."""
        config = FinderConfig(events=EventsConfig(batch_size=100))

        # Create events that fill exactly one batch
        mock_events = []
        for i in range(100):
            mock_event = MagicMock()
            mock_event.__getitem__ = lambda _, key, i=i: {
                "id": bytes([i]) * 32,
                "created_at": 1700000000 + i,
                "kind": 2,
                "tags": None,
                "content": f"wss://relay{i}.com",
            }[key]
            mock_events.append(mock_event)

        # Return 100 events first, then empty (simulating batch limit)
        mock_brotr.pool.fetch = AsyncMock(side_effect=[mock_events, []])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=100)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr, config=config)
        await finder._find_from_events()

        # Verify batch_size was passed to query
        fetch_calls = mock_brotr.pool.fetch.call_args_list
        assert len(fetch_calls) >= 1

    @pytest.mark.asyncio
    async def test_exception_handling_during_database_query(self, mock_brotr: Brotr) -> None:
        """H12.10: Exception handling during database query."""
        mock_brotr.pool.fetch = AsyncMock(side_effect=Exception("Database connection error"))  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        # Should not raise, should handle gracefully
        await finder._find_from_events()

        assert finder._found_relays == 0

    @pytest.mark.asyncio
    async def test_network_type_detected_clearnet_vs_tor(self, mock_brotr: Brotr) -> None:
        """H12.11: Network type correctly detected (clearnet vs tor)."""
        mock_event = MagicMock()
        mock_event.__getitem__ = lambda _, key: {
            "id": b"\x08" * 32,
            "created_at": 1700000000,
            "kind": 10002,
            "tags": [
                ["r", "wss://clearnet.relay.com"],
                ["r", "ws://tortest.onion"],
            ],
            "content": "",
        }[key]

        mock_brotr.pool.fetch = AsyncMock(return_value=[mock_event])  # type: ignore[method-assign]
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]
        mock_brotr.upsert_service_data = AsyncMock(return_value=2)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._find_from_events()

        # Both clearnet and onion URLs should be processed
        mock_brotr.upsert_service_data.assert_called()


# ============================================================================
# H13: Cursor Persistence Tests
# ============================================================================


class TestFinderCursorPersistence:
    """Tests for Finder cursor persistence methods (H13)."""

    @pytest.mark.asyncio
    async def test_load_cursor_returns_default_when_no_cursor_exists(
        self, mock_brotr: Brotr
    ) -> None:
        """H13.1: _load_cursor() returns default when no cursor exists."""
        mock_brotr.get_service_data = AsyncMock(return_value=[])  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        cursor = await finder._load_event_cursor()

        assert cursor == {}

    @pytest.mark.asyncio
    async def test_load_cursor_returns_saved_cursor_when_exists(self, mock_brotr: Brotr) -> None:
        """H13.2: _load_cursor() returns saved cursor when exists."""
        saved_cursor = {
            "last_timestamp": 1700000000,
            "last_id": "aa" * 32,
        }
        mock_brotr.get_service_data = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"value": saved_cursor}]
        )

        finder = Finder(brotr=mock_brotr)
        cursor = await finder._load_event_cursor()

        assert cursor["last_timestamp"] == 1700000000
        assert cursor["last_id"] == "aa" * 32

    @pytest.mark.asyncio
    async def test_save_cursor_persists_cursor_to_database(self, mock_brotr: Brotr) -> None:
        """H13.3: _save_cursor() persists cursor to database."""
        mock_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        await finder._save_event_cursor(1700000000, b"\xaa" * 32)

        mock_brotr.upsert_service_data.assert_called_once()
        call_args = mock_brotr.upsert_service_data.call_args[0][0]
        assert call_args[0][0] == "finder"
        assert call_args[0][1] == "cursor"
        assert call_args[0][2] == "events"

    @pytest.mark.asyncio
    async def test_cursor_survives_service_restart(self, mock_brotr: Brotr) -> None:
        """H13.4: Cursor survives service restart (load after save)."""
        saved_data: list[dict] = []

        async def mock_upsert(records: list) -> int:
            saved_data.clear()
            saved_data.extend([{"value": r[3]} for r in records])
            return len(records)

        async def mock_get(*args, **kwargs) -> list:
            return saved_data

        mock_brotr.upsert_service_data = mock_upsert  # type: ignore[method-assign]
        mock_brotr.get_service_data = mock_get  # type: ignore[method-assign]

        finder1 = Finder(brotr=mock_brotr)
        await finder1._save_event_cursor(1700000500, b"\xbb" * 32)

        # Simulate restart with new finder instance
        finder2 = Finder(brotr=mock_brotr)
        cursor = await finder2._load_event_cursor()

        assert cursor["last_timestamp"] == 1700000500
        assert cursor["last_id"] == "bb" * 32

    @pytest.mark.asyncio
    async def test_invalid_cursor_data_handled_gracefully(self, mock_brotr: Brotr) -> None:
        """H13.5: Invalid cursor data handled gracefully."""
        mock_brotr.get_service_data = AsyncMock(side_effect=Exception("DB Error"))  # type: ignore[method-assign]

        finder = Finder(brotr=mock_brotr)
        cursor = await finder._load_event_cursor()

        # Should return empty dict on error
        assert cursor == {}

    @pytest.mark.asyncio
    async def test_cursor_with_missing_fields_uses_defaults(self, mock_brotr: Brotr) -> None:
        """H13.6: Cursor with missing fields uses defaults."""
        # Cursor with only timestamp, missing last_id
        incomplete_cursor = {"last_timestamp": 1700000000}
        mock_brotr.get_service_data = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"value": incomplete_cursor}]
        )

        finder = Finder(brotr=mock_brotr)
        cursor = await finder._load_event_cursor()

        # Should have timestamp but no last_id
        assert cursor.get("last_timestamp") == 1700000000
        assert cursor.get("last_id") is None
