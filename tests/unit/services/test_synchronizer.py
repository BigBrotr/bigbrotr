"""
Unit tests for services.synchronizer module.

Tests:
- Configuration models (NetworkConfig, FilterConfig, SyncTimeoutsConfig)
- Synchronizer service initialization and defaults
- Relay fetching and metadata-based filtering
- Start time determination from cursors
- EventBatch class (append, is_full, is_empty, time bounds)
- Per-relay timeout overrides
- TaskGroup structured concurrency
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig, BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import NetworkConfig, TorConfig
from bigbrotr.services.synchronizer import (
    EventBatch,
    FilterConfig,
    SourceConfig,
    SyncConcurrencyConfig,
    Synchronizer,
    SynchronizerConfig,
    SyncTimeoutsConfig,
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
# SyncTimeoutsConfig Tests
# ============================================================================


class TestSyncTimeoutsConfig:
    """Tests for SyncTimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default sync timeouts."""
        config = SyncTimeoutsConfig()

        assert config.relay_clearnet == 1800.0
        assert config.relay_tor == 3600.0
        assert config.relay_i2p == 3600.0
        assert config.relay_loki == 3600.0

    def test_get_relay_timeout(self) -> None:
        """Test get_relay_timeout method."""
        config = SyncTimeoutsConfig()

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 1800.0
        assert config.get_relay_timeout(NetworkType.TOR) == 3600.0
        assert config.get_relay_timeout(NetworkType.I2P) == 3600.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 3600.0

    def test_custom_values(self) -> None:
        """Test custom sync timeouts."""
        config = SyncTimeoutsConfig(
            relay_clearnet=900.0,
            relay_tor=1800.0,
        )

        assert config.relay_clearnet == 900.0
        assert config.relay_tor == 1800.0


# ============================================================================
# SyncConcurrencyConfig Tests
# ============================================================================


class TestSyncConcurrencyConfig:
    """Tests for SyncConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = SyncConcurrencyConfig()

        assert config.stagger_delay == (0, 60)
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
        assert config.sync_timeouts.relay_clearnet == 1800.0
        assert config.concurrency.cursor_flush_interval == 50
        assert config.source.from_database is True
        assert config.interval == 300.0

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration with Tor enabled."""
        config = SynchronizerConfig(
            networks=NetworkConfig(tor=TorConfig(enabled=True)),
            concurrency=SyncConcurrencyConfig(cursor_flush_interval=25),
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
            networks=NetworkConfig(tor=TorConfig(enabled=True)),
            concurrency=SyncConcurrencyConfig(cursor_flush_interval=25),
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
    """Tests for Synchronizer._fetch_relays() method."""

    async def test_fetch_relays_empty(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when none available."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync._fetch_relays()

        assert relays == []

    async def test_fetch_relays_disabled(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when source is disabled."""
        config = SynchronizerConfig(source=SourceConfig(from_database=False))
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relays = await sync._fetch_relays()

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
        relays = await sync._fetch_relays()

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
        relays = await sync._fetch_relays()

        assert len(relays) == 1
        assert "valid.relay.com" in str(relays[0].url)


# ============================================================================
# Synchronizer Get Start Time Tests
# ============================================================================


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

        assert sync._synced_relays == 0
        assert sync._synced_events == 0


# ============================================================================
# Synchronizer _sync_all_relays Tests
# ============================================================================


class TestSynchronizerSyncAllRelays:
    """Tests for Synchronizer._sync_all_relays() with TaskGroup."""

    async def test_sync_all_relays_handles_task_group_errors(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test that ExceptionGroup from TaskGroup is handled gracefully."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)

        # Mock _fetch_all_cursors to return empty dict
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        # Create a relay and patch _sync_relay_events to raise an unhandled error
        relay = Relay("wss://failing.relay.com")

        # The worker catches most exceptions, so we need to make the worker
        # itself raise by patching something fundamental
        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            side_effect=RuntimeError("unexpected"),
        ):
            # Should not raise -- errors are caught and logged
            await sync._sync_all_relays([relay])

        # The relay should be counted as failed
        assert sync._failed_relays >= 1

    async def test_sync_all_relays_empty_list(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _sync_all_relays with no relays completes without error."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        await sync._sync_all_relays([])

        assert sync._synced_relays == 0
        assert sync._failed_relays == 0


# ============================================================================
# EventBatch Tests
# ============================================================================


def _make_mock_event(created_at_secs: int) -> MagicMock:
    """Create a mock event with a properly mocked created_at timestamp."""
    event = MagicMock()
    # Create a mock Timestamp that returns the integer when as_secs() is called
    mock_timestamp = MagicMock()
    mock_timestamp.as_secs.return_value = created_at_secs
    event.created_at.return_value = mock_timestamp
    return event


class TestEventBatch:
    """Tests for EventBatch class."""

    def test_init(self) -> None:
        """Test batch initialization."""
        batch = EventBatch(since=100, until=200, limit=10)

        assert batch.since == 100
        assert batch.until == 200
        assert batch.limit == 10
        assert batch.size == 0
        assert batch.events == []
        assert batch.min_created_at is None
        assert batch.max_created_at is None

    def test_append_valid_event(self) -> None:
        """Test appending a valid event."""
        batch = EventBatch(since=100, until=200, limit=10)
        event = _make_mock_event(150)

        batch.append(event)

        assert batch.size == 1
        assert len(batch.events) == 1
        assert batch.min_created_at == 150
        assert batch.max_created_at == 150

    def test_append_multiple_events(self) -> None:
        """Test appending multiple events updates min/max."""
        batch = EventBatch(since=100, until=200, limit=10)

        for ts in [150, 120, 180]:
            event = _make_mock_event(ts)
            batch.append(event)

        assert batch.size == 3
        assert batch.min_created_at == 120
        assert batch.max_created_at == 180

    def test_append_rejects_out_of_bounds(self) -> None:
        """Test that events outside time bounds are rejected."""
        batch = EventBatch(since=100, until=200, limit=10)

        # Event before since
        event1 = _make_mock_event(50)
        batch.append(event1)

        # Event after until
        event2 = _make_mock_event(250)
        batch.append(event2)

        assert batch.size == 0

    def test_append_accepts_boundary_values(self) -> None:
        """Test that events at exact boundaries are accepted."""
        batch = EventBatch(since=100, until=200, limit=10)

        # Event at since
        event1 = _make_mock_event(100)
        batch.append(event1)

        # Event at until
        event2 = _make_mock_event(200)
        batch.append(event2)

        assert batch.size == 2

    def test_append_raises_on_overflow(self) -> None:
        """Test that overflow error is raised when limit reached."""
        batch = EventBatch(since=100, until=200, limit=2)

        event1 = _make_mock_event(150)
        batch.append(event1)

        event2 = _make_mock_event(160)
        batch.append(event2)

        event3 = _make_mock_event(170)

        with pytest.raises(OverflowError, match="Batch limit reached"):
            batch.append(event3)

    def test_is_full(self) -> None:
        """Test is_full method."""
        batch = EventBatch(since=100, until=200, limit=2)

        assert batch.is_full() is False

        event1 = _make_mock_event(150)
        batch.append(event1)
        assert batch.is_full() is False

        event2 = _make_mock_event(160)
        batch.append(event2)
        assert batch.is_full() is True

    def test_is_empty(self) -> None:
        """Test is_empty method."""
        batch = EventBatch(since=100, until=200, limit=10)

        assert batch.is_empty() is True

        event = _make_mock_event(150)
        batch.append(event)
        assert batch.is_empty() is False

    def test_len(self) -> None:
        """Test __len__ method."""
        batch = EventBatch(since=100, until=200, limit=10)

        assert len(batch) == 0

        event1 = _make_mock_event(150)
        batch.append(event1)

        event2 = _make_mock_event(160)
        batch.append(event2)

        assert len(batch) == 2

    def test_iter(self) -> None:
        """Test iteration over batch."""
        batch = EventBatch(since=100, until=200, limit=10)

        event1 = _make_mock_event(150)
        event2 = _make_mock_event(160)

        batch.append(event1)
        batch.append(event2)

        events = list(batch)
        assert len(events) == 2
        assert events[0] is event1
        assert events[1] is event2

    def test_zero_limit(self) -> None:
        """Test batch with zero limit."""
        batch = EventBatch(since=100, until=200, limit=0)

        assert batch.is_full() is True
        assert batch.is_empty() is True

        event = _make_mock_event(150)

        with pytest.raises(OverflowError):
            batch.append(event)
