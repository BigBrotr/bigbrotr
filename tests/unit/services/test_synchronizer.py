"""
Unit tests for services.synchronizer.service module.

Tests:
- Configuration models (FilterConfig, TimeRangeConfig, TimeoutsConfig,
  ConcurrencyConfig, SourceConfig, SynchronizerConfig)
- Synchronizer initialization and factory methods
- Relay fetching from database
- Cursor fetching and start time resolution from cache
- Run cycle orchestration (counter reset, overrides merge, relay dispatch)
- _sync_all_relays structured concurrency (TaskGroup, semaphores,
  cursor flush, overrides, error handling, ExceptionGroup)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.brotr import TimeoutsConfig as BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.configs import NetworksConfig, TorConfig
from bigbrotr.services.common.types import EventRelayCursor
from bigbrotr.services.synchronizer import (
    ConcurrencyConfig,
    FilterConfig,
    RelayOverride,
    RelayOverrideTimeouts,
    SourceConfig,
    Synchronizer,
    SynchronizerConfig,
    TimeoutsConfig,
    TimeRangeConfig,
)


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for all synchronizer tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


@pytest.fixture
def mock_synchronizer_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for synchronizer tests."""
    mock_batch_config = MagicMock()
    mock_batch_config.max_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = BrotrTimeoutsConfig()
    mock_brotr._config = mock_config
    mock_brotr.insert_event_relay = AsyncMock(return_value=0)  # type: ignore[attr-defined]
    mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[attr-defined]
    return mock_brotr


# ============================================================================
# FilterConfig Tests
# ============================================================================


class TestFilterConfig:
    """Tests for FilterConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default filter config."""
        config = FilterConfig()

        assert config.ids is None
        assert config.kinds is None
        assert config.authors is None
        assert config.tags is None
        assert config.limit == 500

    def test_custom_values(self) -> None:
        """Test custom filter config."""
        valid_id1 = "a" * 64
        valid_id2 = "b" * 64
        valid_author = "c" * 64
        config = FilterConfig(
            ids=[valid_id1, valid_id2],
            kinds=[1, 3, 4],
            authors=[valid_author],
            tags={"e": ["event1"]},
            limit=1000,
        )

        assert config.ids == [valid_id1, valid_id2]
        assert config.kinds == [1, 3, 4]
        assert config.authors == [valid_author]
        assert config.tags == {"e": ["event1"]}
        assert config.limit == 1000

    def test_limit_validation(self) -> None:
        """Test limit validation."""
        config = FilterConfig(limit=1)
        assert config.limit == 1

        config = FilterConfig(limit=5000)
        assert config.limit == 5000

        with pytest.raises(ValueError):
            FilterConfig(limit=0)

        with pytest.raises(ValueError):
            FilterConfig(limit=5001)

    def test_kinds_validation_valid_range(self) -> None:
        """Test event kinds within valid range (0-65535)."""
        config = FilterConfig(kinds=[0, 1, 30023, 65535])
        assert config.kinds == [0, 1, 30023, 65535]

    def test_kinds_validation_invalid_range(self) -> None:
        """Test event kinds outside valid range are rejected."""
        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[70000])

        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[-1])

    def test_ids_validation_valid_hex(self) -> None:
        """Test valid 64-character hex strings for IDs."""
        valid_hex = "a" * 64
        config = FilterConfig(ids=[valid_hex])
        assert config.ids == [valid_hex]

    def test_ids_validation_invalid_length(self) -> None:
        """Test IDs with invalid length are rejected."""
        with pytest.raises(ValueError, match="Invalid hex string length"):
            FilterConfig(ids=["short"])

    def test_authors_validation_valid_hex(self) -> None:
        """Test valid 64-character hex strings for authors."""
        valid_hex = "b" * 64
        config = FilterConfig(authors=[valid_hex])
        assert config.authors == [valid_hex]

    def test_authors_validation_invalid_hex_chars(self) -> None:
        """Test authors with invalid hex characters are rejected."""
        with pytest.raises(ValueError, match="Invalid hex string"):
            FilterConfig(authors=["z" * 64])


# ============================================================================
# TimeRangeConfig Tests
# ============================================================================


class TestTimeRangeConfig:
    """Tests for TimeRangeConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default time range config."""
        config = TimeRangeConfig()

        assert config.default_start == 0
        assert config.use_relay_state is True
        assert config.lookback_seconds == 86400

    def test_custom_values(self) -> None:
        """Test custom time range config."""
        config = TimeRangeConfig(
            default_start=1000000,
            use_relay_state=False,
            lookback_seconds=3600,
        )

        assert config.default_start == 1000000
        assert config.use_relay_state is False
        assert config.lookback_seconds == 3600


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default sync timeouts."""
        config = TimeoutsConfig()

        assert config.relay_clearnet == 1800.0
        assert config.relay_tor == 3600.0
        assert config.relay_i2p == 3600.0
        assert config.relay_loki == 3600.0

    def test_get_relay_timeout(self) -> None:
        """Test get_relay_timeout method."""
        config = TimeoutsConfig()

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 1800.0
        assert config.get_relay_timeout(NetworkType.TOR) == 3600.0
        assert config.get_relay_timeout(NetworkType.I2P) == 3600.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 3600.0

    def test_custom_values(self) -> None:
        """Test custom sync timeouts."""
        config = TimeoutsConfig(
            relay_clearnet=900.0,
            relay_tor=1800.0,
        )

        assert config.relay_clearnet == 900.0
        assert config.relay_tor == 1800.0


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.cursor_flush_interval == 50


# ============================================================================
# SourceConfig Tests
# ============================================================================


class TestSourceConfig:
    """Tests for SourceConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default source config."""
        config = SourceConfig()

        assert config.from_database is True

    def test_custom_values(self) -> None:
        """Test custom source config."""
        config = SourceConfig(
            from_database=False,
        )

        assert config.from_database is False


# ============================================================================
# RelayOverrideTimeouts Tests
# ============================================================================


class TestRelayOverrideTimeouts:
    """Tests for RelayOverrideTimeouts Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values are None."""
        config = RelayOverrideTimeouts()
        assert config.request is None
        assert config.relay is None

    def test_valid_values(self) -> None:
        """Test valid timeout values."""
        config = RelayOverrideTimeouts(request=0.1, relay=60.0)
        assert config.request == 0.1
        assert config.relay == 60.0

    def test_zero_timeout_rejected(self) -> None:
        """Test that zero timeout is rejected."""
        with pytest.raises(ValueError):
            RelayOverrideTimeouts(request=0.0)

    def test_negative_timeout_rejected(self) -> None:
        """Test that negative timeout is rejected."""
        with pytest.raises(ValueError):
            RelayOverrideTimeouts(relay=-1.0)


class TestRelayOverride:
    """Tests for RelayOverride Pydantic model."""

    def test_valid(self) -> None:
        """Test valid relay override."""
        config = RelayOverride(url="wss://relay.example.com")
        assert config.url == "wss://relay.example.com"

    def test_empty_url_rejected(self) -> None:
        """Test that empty URL is rejected."""
        with pytest.raises(ValueError):
            RelayOverride(url="")


# ============================================================================
# SynchronizerConfig Tests
# ============================================================================


class TestSynchronizerConfig:
    """Tests for SynchronizerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values (only clearnet enabled)."""
        config = SynchronizerConfig()

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False  # disabled by default
        assert config.filter.limit == 500
        assert config.time_range.default_start == 0
        assert config.networks.clearnet.timeout == 10.0
        assert config.timeouts.relay_clearnet == 1800.0
        assert config.concurrency.cursor_flush_interval == 50
        assert config.source.from_database is True
        assert config.interval == 300.0

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration with Tor enabled."""
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            concurrency=ConcurrencyConfig(cursor_flush_interval=25),
            interval=1800.0,
        )

        assert config.networks.tor.enabled is True
        assert config.concurrency.cursor_flush_interval == 25
        assert config.interval == 1800.0

    def test_no_worker_log_level_field(self) -> None:
        """Test that worker_log_level field has been removed."""
        assert not hasattr(SynchronizerConfig(), "worker_log_level")


# ============================================================================
# Synchronizer Initialization Tests
# ============================================================================


class TestSynchronizerInit:
    """Tests for Synchronizer initialization."""

    def test_init_with_defaults(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test initialization with defaults (only clearnet enabled)."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        assert sync._brotr is mock_synchronizer_brotr
        assert sync.SERVICE_NAME == "synchronizer"
        assert sync.config.networks.clearnet.enabled is True
        assert sync.config.networks.tor.enabled is False

    def test_init_with_custom_config(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test initialization with custom config (Tor enabled)."""
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            concurrency=ConcurrencyConfig(cursor_flush_interval=25),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        assert sync.config.networks.tor.enabled is True
        assert sync.config.concurrency.cursor_flush_interval == 25

    def test_from_dict(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "networks": {"tor": {"enabled": True}},
            "concurrency": {"cursor_flush_interval": 25},
        }
        sync = Synchronizer.from_dict(data, brotr=mock_synchronizer_brotr)

        assert sync.config.networks.tor.enabled is True
        assert sync.config.concurrency.cursor_flush_interval == 25


# ============================================================================
# Synchronizer Fetch Relays Tests
# ============================================================================


class TestSynchronizerFetchRelays:
    """Tests for Synchronizer.fetch_relays() method."""

    async def test_fetch_relays_empty(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when none available."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert relays == []

    async def test_fetch_relays_disabled(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when source is disabled."""
        config = SynchronizerConfig(source=SourceConfig(from_database=False))
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relays = await sync.fetch_relays()

        assert relays == []

    async def test_fetch_relays_with_results(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays from database."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {
                    "url": "wss://relay2.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert len(relays) == 2
        assert "relay1.example.com" in str(relays[0].url)
        assert "relay2.example.com" in str(relays[1].url)

    async def test_fetch_relays_filters_invalid(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays filters invalid URLs."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://valid.relay.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {"url": "invalid-url", "network": "unknown", "discovered_at": 1700000000},
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert len(relays) == 1
        assert "valid.relay.com" in str(relays[0].url)


# ============================================================================
# Synchronizer Fetch Cursors Tests
# ============================================================================


class TestSynchronizerFetchCursors:
    """Tests for Synchronizer.fetch_cursors() method."""

    async def test_returns_empty_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test returns empty dict when use_relay_state is False."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        result = await sync.fetch_cursors()
        assert result == {}

    async def test_delegates_to_get_service_state(self, mock_synchronizer_brotr: Brotr) -> None:
        """Calls brotr.get_service_state when relay_state enabled."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        mock_synchronizer_brotr.get_service_state = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r1.com",
                    state_value={"last_synced_at": 1000},
                    updated_at=1001,
                ),
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r2.com",
                    state_value={"last_synced_at": 2000},
                    updated_at=2001,
                ),
            ]
        )
        result = await sync.fetch_cursors()

        mock_synchronizer_brotr.get_service_state.assert_awaited_once_with(
            ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR
        )
        assert result == {
            "wss://r1.com": EventRelayCursor(relay_url="wss://r1.com", seen_at=1000),
            "wss://r2.com": EventRelayCursor(relay_url="wss://r2.com", seen_at=2000),
        }

    async def test_filters_cursors_with_missing_field(self, mock_synchronizer_brotr: Brotr) -> None:
        """Cursors missing last_synced_at are filtered out."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        mock_synchronizer_brotr.get_service_state = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r1.com",
                    state_value={"last_synced_at": 1000},
                    updated_at=1001,
                ),
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r2.com",
                    state_value={"stale_field": 999},
                    updated_at=1001,
                ),
            ]
        )
        result = await sync.fetch_cursors()

        assert result == {
            "wss://r1.com": EventRelayCursor(relay_url="wss://r1.com", seen_at=1000),
        }


# ============================================================================
# Synchronizer Get Start Time From Cache Tests
# ============================================================================


class TestSynchronizerGetStartTimeFromCache:
    """Tests for Synchronizer._get_start_time_from_cache() method."""

    def test_returns_default_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test returns default_start when use_relay_state is False."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False, default_start=42),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time_from_cache(
            relay,
            {
                "wss://relay.example.com": EventRelayCursor(
                    relay_url="wss://relay.example.com", seen_at=1000
                )
            },
        )
        assert result == 42

    def test_returns_cursor_plus_one_when_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns cursor + 1 when relay has a cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time_from_cache(
            relay,
            {
                "wss://relay.example.com": EventRelayCursor(
                    relay_url="wss://relay.example.com", seen_at=1000
                )
            },
        )
        assert result == 1001

    def test_returns_default_when_cursor_not_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns default_start when relay has no cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=500),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://other.relay.com")

        result = sync._get_start_time_from_cache(
            relay,
            {
                "wss://relay.example.com": EventRelayCursor(
                    relay_url="wss://relay.example.com", seen_at=1000
                )
            },
        )
        assert result == 500

    def test_returns_default_with_empty_cursors(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns default_start with empty cursor cache."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time_from_cache(relay, {})
        assert result == 0


# ============================================================================
# Synchronizer Run Tests
# ============================================================================


class TestSynchronizerRun:
    """Tests for Synchronizer.run() method."""

    async def test_run_no_relays(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run cycle with no relays."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        await sync.run()

        assert sync._counters.synced_relays == 0
        assert sync._counters.synced_events == 0

    async def test_run_with_relays_calls_sync_all(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() with relays fetches them and calls _sync_all_relays."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]

        await sync.run()

        sync._sync_all_relays.assert_called_once()
        relays_arg = sync._sync_all_relays.call_args[0][0]
        assert len(relays_arg) == 1

    async def test_run_merges_overrides(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() merges relay overrides not already in the list."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        config = SynchronizerConfig(
            overrides=[
                RelayOverride(url="wss://override.relay.com"),
            ],
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]

        await sync.run()

        sync._sync_all_relays.assert_called_once()
        relays_arg = sync._sync_all_relays.call_args[0][0]
        assert len(relays_arg) == 2
        urls = {str(r.url) for r in relays_arg}
        assert "wss://override.relay.com" in urls or "wss://override.relay.com/" in urls

    async def test_run_skips_duplicate_override(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() does not duplicate overrides already in DB relays."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        config = SynchronizerConfig(
            overrides=[
                RelayOverride(url="wss://relay1.example.com"),
            ],
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]

        await sync.run()

        relays_arg = sync._sync_all_relays.call_args[0][0]
        assert len(relays_arg) == 1

    async def test_run_handles_invalid_override_url(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() handles invalid override URLs gracefully."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = SynchronizerConfig(
            overrides=[
                RelayOverride(url="not-a-valid-url"),
            ],
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]

        await sync.run()

        # No relays to sync (DB empty + override invalid) -> _sync_all_relays not called
        sync._sync_all_relays.assert_not_called()

    async def test_run_resets_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() resets all counters at the start of each cycle."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._counters.synced_events = 99
        sync._counters.synced_relays = 99
        sync._counters.failed_relays = 99
        sync._counters.invalid_events = 99

        await sync.run()

        assert sync._counters.synced_events == 0
        assert sync._counters.synced_relays == 0
        assert sync._counters.failed_relays == 0
        assert sync._counters.invalid_events == 0


# ============================================================================
# Synchronizer _sync_all_relays Tests
# ============================================================================


class TestSynchronizerSyncAllRelays:
    """Tests for Synchronizer._sync_all_relays() with TaskGroup."""

    async def test_sync_all_relays_empty_list(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _sync_all_relays with no relays completes without error."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        await sync._sync_all_relays([])

        assert sync._counters.synced_relays == 0
        assert sync._counters.failed_relays == 0

    async def test_sync_all_relays_success_updates_counters(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test successful sync increments synced_relays and synced_events."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://success.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 2),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.synced_relays == 1
        assert sync._counters.synced_events == 10
        assert sync._counters.invalid_events == 2

    async def test_sync_all_relays_handles_task_group_errors(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test that ExceptionGroup from TaskGroup is handled gracefully."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            side_effect=RuntimeError("unexpected"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.failed_relays >= 1

    async def test_sync_all_relays_timeout_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test TimeoutError from wait_for increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://slow.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("overall timeout"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.failed_relays == 1
        assert sync._counters.synced_relays == 0

    async def test_sync_all_relays_postgres_error_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test asyncpg.PostgresError increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://db-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("db error"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.failed_relays == 1

    async def test_sync_all_relays_os_error_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test OSError increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://net-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.failed_relays == 1

    async def test_sync_all_relays_cursor_update_flushed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test cursor updates are flushed at end of sync."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=50),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            await sync._sync_all_relays([relay])

        mock_synchronizer_brotr.upsert_service_state.assert_called()

    async def test_sync_all_relays_cursor_periodic_flush(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test cursor updates are periodically flushed when batch size reached."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(
                cursor_flush_interval=1,  # Flush after every relay
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relays = [
            Relay("wss://relay1.example.com"),
            Relay("wss://relay2.example.com"),
        ]

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            await sync._sync_all_relays(relays)

        # Multiple calls: periodic flushes + final flush
        assert mock_synchronizer_brotr.upsert_service_state.call_count >= 2

    async def test_sync_all_relays_final_cursor_flush_error(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test final cursor flush handles DB errors gracefully."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=999),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        mock_synchronizer_brotr.upsert_service_state = AsyncMock(
            side_effect=asyncpg.PostgresError("flush failed")
        )

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            # Should not raise
            await sync._sync_all_relays([relay])

        assert sync._counters.synced_relays == 1

    async def test_sync_all_relays_skip_when_start_ge_end(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test relay is skipped when start_time >= end_time."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(
                default_start=999_999_999_999,  # Far future
                use_relay_state=False,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
        ) as mock_sync:
            await sync._sync_all_relays([relay])

        mock_sync.assert_not_called()
        assert sync._counters.synced_relays == 0

    async def test_sync_all_relays_with_override_timeouts(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test relay override timeouts are applied."""
        config = SynchronizerConfig(
            overrides=[
                RelayOverride(
                    url="wss://relay.example.com",
                    timeouts=RelayOverrideTimeouts(relay=999.0, request=88.0),
                ),
            ],
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(0, 0),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.synced_relays == 1

    async def test_sync_all_relays_with_cached_cursor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay uses cached cursor for start time."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        sync.fetch_cursors = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "wss://relay.example.com": EventRelayCursor(
                    relay_url="wss://relay.example.com", seen_at=100
                ),
            }
        )

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            await sync._sync_all_relays([relay])

        assert sync._counters.synced_relays == 1


# ============================================================================
# Synchronizer Metrics Tests
# ============================================================================


class TestSynchronizerMetrics:
    """Tests for Synchronizer Prometheus metric emission."""

    async def test_run_emits_gauges(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() emits all progress gauges after synchronization."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        await sync.run()

        sync.set_gauge.assert_any_call("total", 1)
        sync.set_gauge.assert_any_call("synced_relays", 0)
        sync.set_gauge.assert_any_call("failed_relays", 0)
        sync.set_gauge.assert_any_call("synced_events", 0)
        sync.set_gauge.assert_any_call("invalid_events", 0)

    async def test_run_no_relays_emits_zero_total(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() emits total=0 gauge when no relays to sync."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        await sync.run()

        sync.set_gauge.assert_any_call("total", 0)

    async def test_sync_single_relay_emits_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _sync_single_relay emits cumulative counters after sync."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 2),
        ):
            await sync._sync_all_relays([relay])

        sync.inc_counter.assert_any_call("total_events_synced", 10)
        sync.inc_counter.assert_any_call("total_events_invalid", 2)

    async def test_sync_failed_relay_no_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test failed relay does not emit event counters."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            await sync._sync_all_relays([relay])

        # No event counters should be emitted for failed relays
        for call in sync.inc_counter.call_args_list:
            assert call[0][0] not in (
                "total_events_synced",
                "total_events_invalid",
            )

    async def test_sync_single_relay_emits_relays_synced_counter(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Successful relay sync emits total_relays_synced counter."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(5, 0),
        ):
            await sync._sync_all_relays([relay])

        sync.inc_counter.assert_any_call("total_relays_synced")

    async def test_sync_failed_relay_emits_relays_failed_counter(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Failed relay sync emits total_relays_failed counter."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            await sync._sync_all_relays([relay])

        sync.inc_counter.assert_any_call("total_relays_failed")

    async def test_synchronize_returns_relay_count(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test synchronize() returns the number of relays processed."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {
                    "url": "wss://relay2.example.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._sync_all_relays = AsyncMock()  # type: ignore[method-assign]

        result = await sync.synchronize()

        assert result == 2

    async def test_synchronize_returns_zero_when_no_relays(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test synchronize() returns 0 when no relays available."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        result = await sync.synchronize()

        assert result == 0


# ============================================================================
# Synchronizer Network Filter Tests
# ============================================================================


class TestSynchronizerNetworkFilter:
    """Tests for network filtering in Synchronizer.fetch_relays()."""

    async def test_fetch_relays_filters_disabled_networks(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Relays on disabled networks are excluded from the result."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://clearnet.relay.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {
                    "url": "ws://hidden.onion",
                    "network": "tor",
                    "discovered_at": 1700000000,
                },
            ]
        )

        # Default config: only clearnet enabled, tor disabled
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert len(relays) == 1
        assert "clearnet.relay.com" in str(relays[0].url)

    async def test_fetch_relays_includes_enabled_tor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Tor relays included when tor network is enabled."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "wss://clearnet.relay.com",
                    "network": "clearnet",
                    "discovered_at": 1700000000,
                },
                {
                    "url": "ws://hidden.onion",
                    "network": "tor",
                    "discovered_at": 1700000000,
                },
            ]
        )

        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relays = await sync.fetch_relays()

        assert len(relays) == 2

    async def test_fetch_relays_returns_empty_when_all_networks_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Returns empty list when all networks are disabled."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {
                    "url": "ws://hidden.onion",
                    "network": "tor",
                    "discovered_at": 1700000000,
                },
            ]
        )

        # Default config: tor disabled, the only relay is tor
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert relays == []


# ============================================================================
# Synchronizer Stale Cursor Cleanup Tests
# ============================================================================


class TestSynchronizerStaleCursorCleanup:
    """Tests for stale cursor cleanup in Synchronizer.synchronize()."""

    async def test_stale_cursors_cleaned_before_fetch_relays(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """cleanup_service_state is called before relay fetch."""
        call_order: list[str] = []

        async def _mock_delete_stale(*args: object, **kwargs: object) -> int:
            call_order.append("cleanup_service_state")
            return 2

        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        with patch(
            "bigbrotr.services.synchronizer.service.cleanup_service_state",
            new_callable=AsyncMock,
            side_effect=_mock_delete_stale,
        ):
            sync = Synchronizer(brotr=mock_synchronizer_brotr)

            original_fetch = sync.fetch_relays

            async def _tracked_fetch() -> list[Relay]:
                call_order.append("fetch_relays")
                return await original_fetch()

            sync.fetch_relays = _tracked_fetch  # type: ignore[method-assign]

            await sync.synchronize()

            assert call_order[0] == "cleanup_service_state"
            assert "fetch_relays" in call_order

    async def test_stale_cursor_cleanup_failure_does_not_block(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Stale cursor cleanup DB error does not prevent synchronization."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        with patch(
            "bigbrotr.services.synchronizer.service.cleanup_service_state",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("cleanup failed"),
        ):
            sync = Synchronizer(brotr=mock_synchronizer_brotr)

            # Should not raise — cleanup failure is non-fatal
            result = await sync.synchronize()
            assert result == 0
