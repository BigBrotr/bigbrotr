"""
Unit tests for Finder service.
"""

import json
import tempfile
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.finder import (
    FINDER_SERVICE_NAME,
    ApiConfig,
    ApiSourceConfig,
    DiscoveryResult,
    EventScanConfig,
    Finder,
    FinderConfig,
    FinderState,
    LoggingConfig,
)

# ============================================================================
# Configuration Model Tests
# ============================================================================


class TestEventScanConfig:
    """Tests for EventScanConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = EventScanConfig()

        assert config.enabled is True
        assert config.batch_size == 1000
        assert config.max_events_per_cycle == 100000

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = EventScanConfig(
            enabled=False,
            batch_size=500,
            max_events_per_cycle=50000,
        )

        assert config.enabled is False
        assert config.batch_size == 500
        assert config.max_events_per_cycle == 50000

    def test_batch_size_validation(self) -> None:
        """Test batch size boundaries."""
        # Valid boundaries
        config = EventScanConfig(batch_size=100)
        assert config.batch_size == 100

        config = EventScanConfig(batch_size=10000)
        assert config.batch_size == 10000

        # Invalid: too small
        with pytest.raises(ValueError):
            EventScanConfig(batch_size=99)

        # Invalid: too large
        with pytest.raises(ValueError):
            EventScanConfig(batch_size=10001)


class TestApiSourceConfig:
    """Tests for ApiSourceConfig Pydantic model."""

    def test_creation(self) -> None:
        """Test creating API source config."""
        config = ApiSourceConfig(url="https://api.example.com/relays")

        assert config.url == "https://api.example.com/relays"
        assert config.enabled is True
        assert config.timeout == 30.0

    def test_custom_values(self) -> None:
        """Test custom values."""
        config = ApiSourceConfig(
            url="https://api.example.com",
            enabled=False,
            timeout=60.0,
        )

        assert config.enabled is False
        assert config.timeout == 60.0


class TestApiConfig:
    """Tests for ApiConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = ApiConfig()

        assert config.enabled is True
        assert len(config.sources) == 2
        assert config.request_delay == 1.0

    def test_default_sources(self) -> None:
        """Test default API sources."""
        config = ApiConfig()

        urls = [s.url for s in config.sources]
        assert "https://api.nostr.watch/v1/online" in urls
        assert "https://api.nostr.watch/v1/offline" in urls

    def test_custom_sources(self) -> None:
        """Test custom API sources."""
        config = ApiConfig(
            sources=[
                ApiSourceConfig(url="https://custom.api/relays"),
            ]
        )

        assert len(config.sources) == 1
        assert config.sources[0].url == "https://custom.api/relays"


class TestFinderServiceName:
    """Tests for FINDER_SERVICE_NAME constant."""

    def test_service_name_value(self) -> None:
        """Test the service name is correctly defined."""
        assert FINDER_SERVICE_NAME == "finder"


class TestLoggingConfig:
    """Tests for LoggingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default values."""
        config = LoggingConfig()

        assert config.log_progress is True
        assert config.log_level == "INFO"
        assert config.progress_interval == 5000

    def test_valid_log_levels(self) -> None:
        """Test valid log levels."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(log_level=level)
            assert config.log_level == level

    def test_case_insensitive(self) -> None:
        """Test log level is normalized to uppercase."""
        config = LoggingConfig(log_level="debug")
        assert config.log_level == "DEBUG"

    def test_invalid_log_level(self) -> None:
        """Test invalid log level raises error."""
        with pytest.raises(ValueError):
            LoggingConfig(log_level="INVALID")


class TestFinderConfig:
    """Tests for FinderConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = FinderConfig()

        assert config.event_scan.enabled is True
        assert config.api.enabled is True
        assert config.insert_batch_size == 100

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
            insert_batch_size=50,
        )

        assert config.event_scan.enabled is False
        assert config.api.enabled is False
        assert config.insert_batch_size == 50


# ============================================================================
# Result and State Dataclass Tests
# ============================================================================


class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""

    def test_creation(self) -> None:
        """Test creating discovery result."""
        result = DiscoveryResult(
            success=True,
            message="Discovery completed",
            relays_found=100,
            relays_inserted=95,
            events_scanned=50000,
            api_sources_checked=2,
            duration_seconds=120.5,
        )

        assert result.success is True
        assert result.relays_found == 100
        assert result.relays_inserted == 95
        assert result.events_scanned == 50000
        assert result.api_sources_checked == 2

    def test_default_values(self) -> None:
        """Test default values."""
        result = DiscoveryResult(success=True, message="OK")

        assert result.relays_found == 0
        assert result.relays_inserted == 0
        assert result.events_scanned == 0
        assert result.errors == []

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = DiscoveryResult(
            success=True,
            message="OK",
            relays_found=50,
            duration_seconds=10.123456,
            errors=["error1"],
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["relays_found"] == 50
        assert data["duration_seconds"] == 10.123
        assert data["errors"] == ["error1"]


class TestFinderState:
    """Tests for FinderState dataclass."""

    def test_creation(self) -> None:
        """Test creating finder state."""
        state = FinderState(
            last_seen_at=1700000000,
            total_events_processed=50000,
            total_relays_found=1000,
            last_run_at=1700000001,
        )

        assert state.last_seen_at == 1700000000
        assert state.total_events_processed == 50000
        assert state.total_relays_found == 1000
        assert state.last_run_at == 1700000001

    def test_default_values(self) -> None:
        """Test default values."""
        state = FinderState()

        assert state.last_seen_at == 0
        assert state.total_events_processed == 0
        assert state.total_relays_found == 0
        assert state.last_run_at == 0

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        state = FinderState(last_seen_at=1000, total_relays_found=50)
        data = state.to_dict()

        assert data["last_seen_at"] == 1000
        assert data["total_relays_found"] == 50

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "last_seen_at": 2000,
            "total_events_processed": 100,
            "total_relays_found": 25,
            "last_run_at": 3000,
        }
        state = FinderState.from_dict(data)

        assert state.last_seen_at == 2000
        assert state.total_events_processed == 100
        assert state.total_relays_found == 25
        assert state.last_run_at == 3000

    def test_from_dict_with_missing_fields(self) -> None:
        """Test from_dict handles missing fields."""
        data = {"last_seen_at": 1000}
        state = FinderState.from_dict(data)

        assert state.last_seen_at == 1000
        assert state.total_events_processed == 0
        assert state.total_relays_found == 0


# ============================================================================
# Finder Service Tests
# ============================================================================


class TestFinder:
    """Tests for Finder service class."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance with mock pool."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.fixture
    def finder(self, mock_brotr: MagicMock) -> Finder:
        """Create Finder with mocked dependencies."""
        return Finder(brotr=mock_brotr)

    def test_init_default_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with default config."""
        finder = Finder(brotr=mock_brotr)

        assert finder._brotr is mock_brotr
        assert finder._config is not None
        assert finder._is_running is False
        assert finder._state.last_seen_at == 0

    def test_init_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            insert_batch_size=50,
        )
        finder = Finder(brotr=mock_brotr, config=config)

        assert finder._config.event_scan.enabled is False
        assert finder._config.insert_batch_size == 50

    def test_repr(self, finder: Finder) -> None:
        """Test string representation."""
        repr_str = repr(finder)
        assert "Finder" in repr_str
        assert "is_running=False" in repr_str

    @pytest.mark.asyncio
    async def test_start_stop(self, finder: Finder) -> None:
        """Test start and stop methods."""
        assert finder.is_running is False

        await finder.start()
        assert finder.is_running is True

        await finder.stop()
        assert finder.is_running is False

    @pytest.mark.asyncio
    async def test_health_check_success(self, finder: Finder) -> None:
        """Test health check returns True on success."""
        result = await finder.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_brotr: MagicMock) -> None:
        """Test health check returns False on failure."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection failed"))
        finder = Finder(brotr=mock_brotr)

        result = await finder.health_check()
        assert result is False

    def test_config_property(self, finder: Finder) -> None:
        """Test config property returns config."""
        config = finder.config
        assert isinstance(config, FinderConfig)

    def test_state_property(self, finder: Finder) -> None:
        """Test state property returns state."""
        state = finder.state
        assert isinstance(state, FinderState)


class TestFinderStateManagement:
    """Tests for Finder state management."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_load_state_empty(self, mock_brotr: MagicMock) -> None:
        """Test loading state when no state exists."""
        mock_brotr.pool.fetchrow = AsyncMock(return_value=None)
        finder = Finder(brotr=mock_brotr)

        await finder._load_state()

        assert finder._state.last_seen_at == 0
        assert finder._state.total_events_processed == 0

    @pytest.mark.asyncio
    async def test_load_state_existing(self, mock_brotr: MagicMock) -> None:
        """Test loading existing state."""
        state_data = {
            "last_seen_at": 1700000000,
            "total_events_processed": 50000,
            "total_relays_found": 1000,
            "last_run_at": 1700000001,
        }
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"state": state_data})
        finder = Finder(brotr=mock_brotr)

        await finder._load_state()

        assert finder._state.last_seen_at == 1700000000
        assert finder._state.total_events_processed == 50000
        assert finder._state.total_relays_found == 1000

    @pytest.mark.asyncio
    async def test_load_state_json_string(self, mock_brotr: MagicMock) -> None:
        """Test loading state when stored as JSON string."""
        state_data = json.dumps({
            "last_seen_at": 1700000000,
            "total_events_processed": 50000,
        })
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"state": state_data})
        finder = Finder(brotr=mock_brotr)

        await finder._load_state()

        assert finder._state.last_seen_at == 1700000000

    @pytest.mark.asyncio
    async def test_load_state_error(self, mock_brotr: MagicMock) -> None:
        """Test loading state handles errors gracefully."""
        mock_brotr.pool.fetchrow = AsyncMock(side_effect=Exception("DB error"))
        finder = Finder(brotr=mock_brotr)

        await finder._load_state()

        # Should use default state on error
        assert finder._state.last_seen_at == 0

    @pytest.mark.asyncio
    async def test_save_state(self, mock_brotr: MagicMock) -> None:
        """Test saving state to database."""
        finder = Finder(brotr=mock_brotr)
        finder._state.last_seen_at = 1700000000
        finder._state.total_relays_found = 100

        await finder._save_state()

        mock_brotr.pool.execute.assert_called_once()
        call_args = mock_brotr.pool.execute.call_args[0]
        assert "INSERT INTO service_state" in call_args[0]
        assert call_args[1] == "finder"

    @pytest.mark.asyncio
    async def test_save_state_error(self, mock_brotr: MagicMock) -> None:
        """Test save state handles errors gracefully."""
        mock_brotr.pool.execute = AsyncMock(side_effect=Exception("DB error"))
        finder = Finder(brotr=mock_brotr)

        # Should not raise
        await finder._save_state()


class TestFinderApiSources:
    """Tests for Finder API fetching."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_fetch_api_source_success(self, mock_brotr: MagicMock) -> None:
        """Test fetching from API source."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.test.com/relays")

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=[
            "wss://relay1.example.com",
            "wss://relay2.example.com",
        ])

        with patch("aiohttp.ClientSession") as mock_session:
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock()

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=mock_context)
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_instance

            urls = await finder._fetch_api_source(source)

        assert len(urls) == 2
        assert "wss://relay1.example.com" in urls
        assert "wss://relay2.example.com" in urls

    @pytest.mark.asyncio
    async def test_fetch_api_source_filters_invalid(self, mock_brotr: MagicMock) -> None:
        """Test that invalid URLs are filtered out."""
        finder = Finder(brotr=mock_brotr)
        source = ApiSourceConfig(url="https://api.test.com/relays")

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = AsyncMock(return_value=[
            "wss://valid.relay.com",
            "http://invalid.com",  # Not wss://
            "wss://another.valid.com",
            123,  # Not a string
        ])

        with patch("aiohttp.ClientSession") as mock_session:
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock()

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=mock_context)
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock()

            mock_session.return_value = mock_session_instance

            urls = await finder._fetch_api_source(source)

        assert len(urls) == 2
        assert "wss://valid.relay.com" in urls
        assert "wss://another.valid.com" in urls


class TestFinderEventScanning:
    """Tests for Finder event scanning with atomic batch processing."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_scan_events_extracts_urls(self, mock_brotr: MagicMock) -> None:
        """Test scan_events extracts URLs from event content."""
        # Mock returning events with relay URLs
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    {"event_id": b"test1", "seen_at": 1000, "content": "Check wss://relay.damus.io"},
                    {"event_id": b"test2", "seen_at": 1001, "content": "Also wss://nos.lol here"},
                ],
                [],  # Second call returns empty to stop loop
            ]
        )

        # Mock transaction context manager
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_brotr.pool.transaction = MagicMock(return_value=AsyncContextManager(mock_conn))

        finder = Finder(brotr=mock_brotr)
        result = await finder._scan_events()

        assert result["events_scanned"] == 2
        assert "wss://relay.damus.io" in finder._found_urls
        assert "wss://nos.lol" in finder._found_urls

    @pytest.mark.asyncio
    async def test_scan_events_respects_watermark(self, mock_brotr: MagicMock) -> None:
        """Test scan_events uses watermark from state."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        finder = Finder(brotr=mock_brotr)
        finder._state.last_seen_at = 5000

        await finder._scan_events()

        # Check watermark was used in query
        call_args = mock_brotr.pool.fetch.call_args[0]
        assert call_args[1] == 5000  # watermark value

    @pytest.mark.asyncio
    async def test_scan_events_handles_empty_content(self, mock_brotr: MagicMock) -> None:
        """Test scan_events handles empty event content."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [{"event_id": b"test1", "seen_at": 1000, "content": ""}],
                [],
            ]
        )

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_brotr.pool.transaction = MagicMock(return_value=AsyncContextManager(mock_conn))

        finder = Finder(brotr=mock_brotr)
        result = await finder._scan_events()

        assert result["events_scanned"] == 1
        assert len(finder._found_urls) == 0


class TestFinderAtomicBatchCommit:
    """Tests for Finder atomic batch commit."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        return brotr

    @pytest.mark.asyncio
    async def test_commit_batch_atomic_inserts_relays_and_updates_watermark(
        self, mock_brotr: MagicMock
    ) -> None:
        """Test atomic batch commits both relays and watermark."""
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_brotr.pool.transaction = MagicMock(return_value=AsyncContextManager(mock_conn))

        finder = Finder(brotr=mock_brotr)
        urls = {"wss://relay.damus.io", "wss://nos.lol"}

        inserted = await finder._commit_batch_atomic(urls, new_watermark=2000, events_in_batch=5)

        # Should insert relays
        assert inserted == 2
        # Should update state
        assert finder._state.last_seen_at == 2000
        assert finder._state.total_events_processed == 5
        # Verify transaction was used
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_commit_batch_atomic_handles_empty_urls(self, mock_brotr: MagicMock) -> None:
        """Test atomic batch handles empty URL set."""
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_brotr.pool.transaction = MagicMock(return_value=AsyncContextManager(mock_conn))

        finder = Finder(brotr=mock_brotr)

        inserted = await finder._commit_batch_atomic(set(), new_watermark=3000, events_in_batch=10)

        assert inserted == 0
        assert finder._state.last_seen_at == 3000
        assert finder._state.total_events_processed == 10

    @pytest.mark.asyncio
    async def test_commit_batch_atomic_skips_invalid_urls(self, mock_brotr: MagicMock) -> None:
        """Test atomic batch skips invalid relay URLs."""
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_brotr.pool.transaction = MagicMock(return_value=AsyncContextManager(mock_conn))

        finder = Finder(brotr=mock_brotr)
        # Mix of valid and invalid URLs
        urls = {"wss://valid.relay.com", "invalid-not-a-url", "wss://another.valid.com"}

        inserted = await finder._commit_batch_atomic(urls, new_watermark=4000, events_in_batch=3)

        # Only valid URLs should be inserted
        assert inserted == 2


# Helper class for mocking async context manager
class AsyncContextManager:
    """Mock async context manager for transactions."""

    def __init__(self, conn: MagicMock) -> None:
        self.conn = conn

    async def __aenter__(self) -> MagicMock:
        return self.conn

    async def __aexit__(self, *args: Any) -> None:
        pass


class TestFinderRelayInsertion:
    """Tests for Finder relay insertion."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_insert_empty_urls(self, mock_brotr: MagicMock) -> None:
        """Test inserting empty URL set."""
        finder = Finder(brotr=mock_brotr)
        finder._found_urls = set()

        inserted = await finder._insert_discovered_relays()

        assert inserted == 0
        mock_brotr.insert_relays.assert_not_called()

    @pytest.mark.asyncio
    async def test_insert_relays_batched(self, mock_brotr: MagicMock) -> None:
        """Test inserting relays in batches."""
        config = FinderConfig(insert_batch_size=50)
        finder = Finder(brotr=mock_brotr, config=config)

        # 120 URLs should be 3 batches (50 + 50 + 20)
        finder._found_urls = {f"wss://relay{i}.example.com" for i in range(120)}

        inserted = await finder._insert_discovered_relays()

        assert inserted == 120
        assert mock_brotr.insert_relays.call_count == 3

    @pytest.mark.asyncio
    async def test_insert_relays_network_detection(self, mock_brotr: MagicMock) -> None:
        """Test network is auto-detected for relays."""
        finder = Finder(brotr=mock_brotr)
        finder._found_urls = {
            "wss://relay.damus.io",
            "wss://2jsnlhfnelig5acq6iacydmzdbdmg7xwunm4xl6qwbvzacw4lwrjmlyd.onion",
        }

        await finder._insert_discovered_relays()

        call_args = mock_brotr.insert_relays.call_args[0][0]
        networks = {r["network"] for r in call_args}
        assert "clearnet" in networks
        assert "tor" in networks


class TestFinderDiscovery:
    """Tests for complete discovery cycle."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr for successful discovery."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        # Return initializer state as initialized when checking for "initializer"
        # Return None for finder state (not yet initialized)
        async def mock_fetchrow(
            query: str, service_name: str, **kwargs: Any
        ) -> Optional[dict[str, Any]]:
            if service_name == "initializer":
                return {"state": {"initialized": True, "initialized_at": 1700000000}}
            return None  # Finder state not found
        brotr.pool.fetchrow = AsyncMock(side_effect=mock_fetchrow)
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_discover_with_everything_disabled(self, mock_brotr: MagicMock) -> None:
        """Test discovery with all sources disabled."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        result = await finder.discover()

        assert result.success is True
        assert result.relays_found == 0
        assert result.events_scanned == 0
        assert result.api_sources_checked == 0

    @pytest.mark.asyncio
    async def test_discover_updates_state(self, mock_brotr: MagicMock) -> None:
        """Test discovery updates state."""
        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=mock_brotr, config=config)

        initial_run_at = finder._state.last_run_at

        await finder.discover()

        assert finder._state.last_run_at > initial_run_at

    @pytest.mark.asyncio
    async def test_discover_fails_without_initializer(self) -> None:
        """Test discovery fails if initializer hasn't completed."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)  # No initializer state
        brotr.pool.fetchval = AsyncMock(return_value=1)
        brotr.pool.execute = AsyncMock()

        config = FinderConfig(
            event_scan=EventScanConfig(enabled=False),
            api=ApiConfig(enabled=False),
        )
        finder = Finder(brotr=brotr, config=config)

        result = await finder.discover()

        assert result.success is False
        assert "initializer" in result.message.lower()


class TestFinderFactory:
    """Tests for Finder factory methods."""

    def test_from_dict(self) -> None:
        """Test creating Finder from dictionary."""
        data = {
            "event_scan": {"enabled": False},
            "api": {"enabled": False},
            "insert_batch_size": 50,
        }

        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        finder = Finder.from_dict(data, brotr=mock_brotr)

        assert finder._config.event_scan.enabled is False
        assert finder._config.api.enabled is False
        assert finder._config.insert_batch_size == 50

    def test_from_yaml(self) -> None:
        """Test creating Finder from YAML file."""
        yaml_content = """
event_scan:
  enabled: true
  batch_size: 500
  max_events_per_cycle: 50000

api:
  enabled: false

insert_batch_size: 25
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        finder = Finder.from_yaml(temp_path, brotr=mock_brotr)

        assert finder._config.event_scan.enabled is True
        assert finder._config.event_scan.batch_size == 500
        assert finder._config.event_scan.max_events_per_cycle == 50000
        assert finder._config.api.enabled is False
        assert finder._config.insert_batch_size == 25
