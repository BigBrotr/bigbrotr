"""
Unit tests for Synchronizer service.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from nostr_tools import Relay

from core.brotr import Brotr, BrotrConfig
from core.pool import Pool
from services.synchronizer import (
    ConcurrencyConfig,
    FilterConfig,
    NetworkTimeoutsConfig,
    RawEventBatch,
    SourceConfig,
    Synchronizer,
    SynchronizerConfig,
    TimeoutsConfig,
    TimeRangeConfig,
    TorConfig,
    _create_filter,
)


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock pool."""
    os.environ.setdefault("DB_PASSWORD", "test_password")
    pool = MagicMock(spec=Pool)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=1)
    pool.execute = AsyncMock(return_value="OK")
    pool.is_connected = True

    # Mock transaction
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value="OK")

    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    pool.transaction = MagicMock(return_value=mock_transaction)

    return pool


@pytest.fixture
def mock_brotr(mock_pool: MagicMock) -> MagicMock:
    """Create a mock Brotr with pool."""
    brotr = MagicMock(spec=Brotr)
    brotr.pool = mock_pool
    brotr.insert_events = AsyncMock(return_value=True)

    # Mock config with batch settings
    mock_batch_config = MagicMock()
    mock_batch_config.max_batch_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    brotr.config = mock_config

    return brotr


class TestSynchronizerConfig:
    """Tests for SynchronizerConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SynchronizerConfig()

        assert config.tor.enabled is True
        assert config.tor.host == "127.0.0.1"
        assert config.tor.port == 9050
        assert config.filter.ids is None
        assert config.filter.kinds is None
        assert config.filter.authors is None
        assert config.filter.tags is None
        assert config.filter.limit == 500
        assert config.time_range.default_start == 0
        assert config.time_range.use_relay_state is True
        assert config.time_range.lookback_seconds == 86400
        assert config.timeouts.clearnet.request == 30.0
        assert config.timeouts.clearnet.relay == 1800.0
        assert config.timeouts.tor.request == 60.0
        assert config.timeouts.tor.relay == 3600.0
        assert config.concurrency.max_parallel == 10
        assert config.concurrency.stagger_delay == (0, 60)
        assert config.source.from_database is True
        assert config.source.max_metadata_age == 43200
        assert config.source.require_readable is True
        assert config.interval == 900.0

    def test_custom_tor(self) -> None:
        """Test custom Tor proxy settings."""
        config = SynchronizerConfig(tor=TorConfig(enabled=False, host="tor", port=9150))

        assert config.tor.enabled is False
        assert config.tor.host == "tor"
        assert config.tor.port == 9150

    def test_custom_filter(self) -> None:
        """Test custom filter settings."""
        config = SynchronizerConfig(
            filter=FilterConfig(
                ids=["abc123"],
                kinds=[1, 3],
                authors=["pubkey1"],
                tags={"e": ["event1"], "p": ["pubkey2"]},
                limit=1000,
            )
        )

        assert config.filter.ids == ["abc123"]
        assert config.filter.kinds == [1, 3]
        assert config.filter.authors == ["pubkey1"]
        assert config.filter.tags == {"e": ["event1"], "p": ["pubkey2"]}
        assert config.filter.limit == 1000

    def test_custom_time_range(self) -> None:
        """Test custom time range settings."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(default_start=1000000, use_relay_state=False)
        )

        assert config.time_range.default_start == 1000000
        assert config.time_range.use_relay_state is False

    def test_custom_timeouts(self) -> None:
        """Test custom timeouts settings."""
        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(
                clearnet=NetworkTimeoutsConfig(request=60.0, relay=3600.0),
                tor=NetworkTimeoutsConfig(request=120.0, relay=7200.0),
            )
        )

        assert config.timeouts.clearnet.request == 60.0
        assert config.timeouts.clearnet.relay == 3600.0
        assert config.timeouts.tor.request == 120.0
        assert config.timeouts.tor.relay == 7200.0

    def test_custom_concurrency(self) -> None:
        """Test custom concurrency settings."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(
                max_parallel=5,
                stagger_delay=(10, 30),
            )
        )

        assert config.concurrency.max_parallel == 5
        assert config.concurrency.stagger_delay == (10, 30)

    def test_custom_source(self) -> None:
        """Test custom source settings."""
        config = SynchronizerConfig(
            source=SourceConfig(
                from_database=False,
                max_metadata_age=3600,
                require_readable=False,
            )
        )

        assert config.source.from_database is False
        assert config.source.max_metadata_age == 3600
        assert config.source.require_readable is False


class TestTorConfig:
    """Tests for TorConfig."""

    def test_default_values(self) -> None:
        """Test default Tor proxy config."""
        config = TorConfig()

        assert config.enabled is True
        assert config.host == "127.0.0.1"
        assert config.port == 9050

    def test_port_validation(self) -> None:
        """Test port validation."""
        config = TorConfig(port=9150)
        assert config.port == 9150

        with pytest.raises(ValueError):
            TorConfig(port=0)

        with pytest.raises(ValueError):
            TorConfig(port=70000)


class TestFilterConfig:
    """Tests for FilterConfig."""

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
        config = FilterConfig(
            ids=["id1", "id2"],
            kinds=[1, 3, 4],
            authors=["author1"],
            tags={"e": ["event1"]},
            limit=1000,
        )

        assert config.ids == ["id1", "id2"]
        assert config.kinds == [1, 3, 4]
        assert config.authors == ["author1"]
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


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig (network-specific)."""

    def test_default_values(self) -> None:
        """Test default timeouts config."""
        config = TimeoutsConfig()

        # Clearnet defaults
        assert config.clearnet.request == 30.0
        assert config.clearnet.relay == 1800.0
        # Tor defaults (higher)
        assert config.tor.request == 60.0
        assert config.tor.relay == 3600.0

    def test_validation(self) -> None:
        """Test validation constraints on NetworkTimeoutsConfig."""
        config = NetworkTimeoutsConfig(request=5.0, relay=60.0)
        assert config.request == 5.0

        with pytest.raises(ValueError):
            NetworkTimeoutsConfig(request=4.0)  # Below minimum

        with pytest.raises(ValueError):
            NetworkTimeoutsConfig(relay=59.0)  # Below minimum


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.max_parallel == 10
        assert config.stagger_delay == (0, 60)

    def test_validation(self) -> None:
        """Test validation constraints."""
        config = ConcurrencyConfig(
            max_parallel=1,
        )
        assert config.max_parallel == 1

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=101)


class TestSourceConfig:
    """Tests for SourceConfig."""

    def test_default_values(self) -> None:
        """Test default source config."""
        config = SourceConfig()

        assert config.from_database is True
        assert config.max_metadata_age == 43200
        assert config.require_readable is True

    def test_custom_values(self) -> None:
        """Test custom source config."""
        config = SourceConfig(
            from_database=False,
            max_metadata_age=0,
            require_readable=False,
        )

        assert config.from_database is False
        assert config.max_metadata_age == 0
        assert config.require_readable is False


class TestSynchronizer:
    """Tests for Synchronizer service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        sync = Synchronizer(brotr=mock_brotr)

        assert sync._brotr is mock_brotr
        assert sync._brotr.pool is mock_brotr.pool
        assert sync.SERVICE_NAME == "synchronizer"
        assert sync.config.tor.enabled is True

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = SynchronizerConfig(
            tor=TorConfig(enabled=False),
            concurrency=ConcurrencyConfig(max_parallel=5),
        )
        sync = Synchronizer(brotr=mock_brotr, config=config)

        assert sync.config.tor.enabled is False
        assert sync.config.concurrency.max_parallel == 5

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_brotr: MagicMock) -> None:
        """Test health check when connected."""
        mock_brotr.pool.fetchval = AsyncMock(return_value=1)

        sync = Synchronizer(brotr=mock_brotr)
        result = await sync.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_brotr: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        sync = Synchronizer(brotr=mock_brotr)
        result = await sync.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_fetch_relays_empty(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays when none available."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        sync = Synchronizer(brotr=mock_brotr)
        relays = await sync._fetch_relays()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_from_database_disabled(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays when database source is disabled."""
        config = SynchronizerConfig(source=SourceConfig(from_database=False))
        sync = Synchronizer(brotr=mock_brotr, config=config)
        relays = await sync._fetch_relays()

        assert relays == []
        mock_brotr.pool.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_relays_with_relays(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays from database."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://relay1.example.com"},
                {"relay_url": "wss://relay2.example.com"},
            ]
        )

        sync = Synchronizer(brotr=mock_brotr)
        relays = await sync._fetch_relays()

        assert len(relays) == 2
        # URL normalization depends on nostr_tools implementation
        assert "relay1.example.com" in relays[0].url
        assert "relay2.example.com" in relays[1].url

    @pytest.mark.asyncio
    async def test_fetch_relays_invalid_url(self, mock_brotr: MagicMock) -> None:
        """Test fetching relays with invalid URL."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"relay_url": "wss://valid.relay.com"},
                {"relay_url": "invalid-url"},
            ]
        )

        sync = Synchronizer(brotr=mock_brotr)
        relays = await sync._fetch_relays()

        # Only valid relay should be returned
        assert len(relays) == 1
        assert "valid.relay.com" in relays[0].url

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_brotr: MagicMock) -> None:
        """Test run cycle with no relays."""
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        sync = Synchronizer(brotr=mock_brotr)
        await sync.run()

        # Should complete without error
        assert sync._synced_relays == 0
        assert sync._synced_events == 0

    @pytest.mark.asyncio
    async def test_get_start_time_default(self, mock_brotr: MagicMock) -> None:
        """Test get start time with default."""
        mock_brotr.pool.fetchrow = AsyncMock(return_value=None)

        config = SynchronizerConfig(
            time_range=TimeRangeConfig(default_start=1000, use_relay_state=False)
        )
        sync = Synchronizer(brotr=mock_brotr, config=config)

        # Mock relay
        relay = Relay("wss://test.relay.com")

        start_time = await sync._get_start_time(relay)
        assert start_time == 1000

    @pytest.mark.asyncio
    async def test_get_start_time_from_state(self, mock_brotr: MagicMock) -> None:
        """Test get start time from persisted state."""
        relay = Relay("wss://test.relay.com")

        sync = Synchronizer(brotr=mock_brotr)
        # Use actual URL from relay object (may or may not have trailing slash)
        sync._state = {"relay_timestamps": {relay.url: 5000}}

        start_time = await sync._get_start_time(relay)
        assert start_time == 5001  # +1 from stored timestamp

    @pytest.mark.asyncio
    async def test_get_start_time_from_database(self, mock_brotr: MagicMock) -> None:
        """Test get start time from database when not in state."""
        mock_brotr.pool.fetchrow = AsyncMock(
            side_effect=[
                {"max_seen": 12345},
                {"created_at": 12000},
            ]
        )

        sync = Synchronizer(brotr=mock_brotr)
        sync._state = {}

        relay = Relay("wss://test.relay.com")

        start_time = await sync._get_start_time(relay)
        assert start_time == 12001  # created_at + 1

    def test_create_filter_basic(self, mock_brotr: MagicMock) -> None:
        """Test creating basic filter."""
        filter_config = FilterConfig()
        filter_obj = _create_filter(since=100, until=200, config=filter_config)

        assert filter_obj.since == 100
        assert filter_obj.until == 200
        assert filter_obj.limit == 500

    def test_create_filter_with_config(self, mock_brotr: MagicMock) -> None:
        """Test creating filter with config values."""
        filter_config = FilterConfig(
            ids=["id1"],
            kinds=[1, 3],
            authors=["author1"],
            limit=100,
        )
        filter_obj = _create_filter(since=100, until=200, config=filter_config)

        assert filter_obj.ids == ["id1"]
        assert filter_obj.kinds == [1, 3]
        assert filter_obj.authors == ["author1"]
        assert filter_obj.limit == 100


class TestSynchronizerFactoryMethods:
    """Tests for Synchronizer factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "tor": {"enabled": False},
            "concurrency": {"max_parallel": 5},
        }

        sync = Synchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.tor.enabled is False
        assert sync.config.concurrency.max_parallel == 5

    def test_from_dict_with_filter(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary with filter."""
        data = {
            "filter": {
                "kinds": [1, 3],
                "tags": {"e": ["event1"]},
            },
        }

        sync = Synchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.filter.kinds == [1, 3]
        assert sync.config.filter.tags == {"e": ["event1"]}

    def test_from_dict_partial(self, mock_brotr: MagicMock) -> None:
        """Test creation from partial dictionary."""
        data = {
            "interval": 1800.0,
        }

        sync = Synchronizer.from_dict(data, brotr=mock_brotr)

        assert sync.config.interval == 1800.0
        # Defaults should be preserved
        assert sync.config.tor.enabled is True


class TestRawEventBatch:
    """Tests for RawEventBatch class."""

    def test_init(self) -> None:
        """Test batch initialization."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        assert batch.since == 100
        assert batch.until == 200
        assert batch.limit == 10
        assert batch.size == 0
        assert batch.raw_events == []
        assert batch.min_created_at is None
        assert batch.max_created_at is None

    def test_append_valid_event(self) -> None:
        """Test appending a valid event."""
        batch = RawEventBatch(since=100, until=200, limit=10)
        event = {"id": "abc", "created_at": 150, "content": "test"}

        batch.append(event)

        assert batch.size == 1
        assert len(batch.raw_events) == 1
        assert batch.min_created_at == 150
        assert batch.max_created_at == 150

    def test_append_multiple_events(self) -> None:
        """Test appending multiple events updates min/max."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        batch.append({"created_at": 150})
        batch.append({"created_at": 120})
        batch.append({"created_at": 180})

        assert batch.size == 3
        assert batch.min_created_at == 120
        assert batch.max_created_at == 180

    def test_append_rejects_non_dict(self) -> None:
        """Test that non-dict events are rejected."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        batch.append("not a dict")  # type: ignore
        batch.append(123)  # type: ignore
        batch.append(None)  # type: ignore

        assert batch.size == 0

    def test_append_rejects_invalid_created_at(self) -> None:
        """Test that events with invalid created_at are rejected."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        batch.append({"content": "no created_at"})
        batch.append({"created_at": "not an int"})
        batch.append({"created_at": -1})

        assert batch.size == 0

    def test_append_rejects_out_of_bounds(self) -> None:
        """Test that events outside time bounds are rejected."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        batch.append({"created_at": 50})  # Before since
        batch.append({"created_at": 250})  # After until

        assert batch.size == 0

    def test_append_accepts_boundary_values(self) -> None:
        """Test that events at exact boundaries are accepted."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        batch.append({"created_at": 100})  # Exactly at since
        batch.append({"created_at": 200})  # Exactly at until

        assert batch.size == 2

    def test_append_raises_on_overflow(self) -> None:
        """Test that overflow error is raised when limit reached."""
        batch = RawEventBatch(since=100, until=200, limit=2)

        batch.append({"created_at": 150})
        batch.append({"created_at": 160})

        with pytest.raises(OverflowError, match="Batch limit reached"):
            batch.append({"created_at": 170})

    def test_is_full(self) -> None:
        """Test is_full method."""
        batch = RawEventBatch(since=100, until=200, limit=2)

        assert batch.is_full() is False

        batch.append({"created_at": 150})
        assert batch.is_full() is False

        batch.append({"created_at": 160})
        assert batch.is_full() is True

    def test_is_empty(self) -> None:
        """Test is_empty method."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        assert batch.is_empty() is True

        batch.append({"created_at": 150})
        assert batch.is_empty() is False

    def test_len(self) -> None:
        """Test __len__ method."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        assert len(batch) == 0

        batch.append({"created_at": 150})
        batch.append({"created_at": 160})

        assert len(batch) == 2

    def test_iter(self) -> None:
        """Test iteration over batch."""
        batch = RawEventBatch(since=100, until=200, limit=10)

        event1 = {"created_at": 150, "id": "1"}
        event2 = {"created_at": 160, "id": "2"}

        batch.append(event1)
        batch.append(event2)

        events = list(batch)
        assert len(events) == 2
        assert events[0] == event1
        assert events[1] == event2

    def test_zero_limit(self) -> None:
        """Test batch with zero limit."""
        batch = RawEventBatch(since=100, until=200, limit=0)

        assert batch.is_full() is True
        assert batch.is_empty() is True

        with pytest.raises(OverflowError):
            batch.append({"created_at": 150})

    def test_same_since_until(self) -> None:
        """Test batch where since equals until."""
        batch = RawEventBatch(since=150, until=150, limit=10)

        batch.append({"created_at": 150})
        assert batch.size == 1

        batch.append({"created_at": 149})  # Below
        batch.append({"created_at": 151})  # Above
        assert batch.size == 1
