"""
Unit tests for services.synchronizer module.

Tests:
- Configuration models (TorConfig, FilterConfig, TimeoutsConfig, etc.)
- Synchronizer service initialization
- Relay fetching and filtering
- Start time determination
- RawEventBatch class
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from nostr_tools import Relay

from core.brotr import Brotr, BrotrConfig
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


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_synchronizer_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for synchronizer tests."""
    mock_batch_config = MagicMock()
    mock_batch_config.max_batch_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_brotr._config = mock_config
    mock_brotr.insert_events = AsyncMock(return_value=0)  # type: ignore[attr-defined]
    return mock_brotr


# ============================================================================
# TorConfig Tests
# ============================================================================


class TestSyncTorConfig:
    """Tests for TorConfig Pydantic model."""

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
# NetworkTimeoutsConfig Tests
# ============================================================================


class TestNetworkTimeoutsConfig:
    """Tests for NetworkTimeoutsConfig Pydantic model."""

    def test_default_clearnet(self) -> None:
        """Test default clearnet timeouts."""
        config = TimeoutsConfig()

        assert config.clearnet.request == 30.0
        assert config.clearnet.relay == 1800.0

    def test_default_tor(self) -> None:
        """Test default tor timeouts."""
        config = TimeoutsConfig()

        assert config.tor.request == 60.0
        assert config.tor.relay == 3600.0

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            NetworkTimeoutsConfig(request=4.0)  # Below minimum

        with pytest.raises(ValueError):
            NetworkTimeoutsConfig(relay=59.0)  # Below minimum


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestSyncConcurrencyConfig:
    """Tests for ConcurrencyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default concurrency config."""
        config = ConcurrencyConfig()

        assert config.max_parallel == 10
        assert config.stagger_delay == (0, 60)

    def test_validation_constraints(self) -> None:
        """Test validation constraints."""
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=101)


# ============================================================================
# SourceConfig Tests
# ============================================================================


class TestSourceConfig:
    """Tests for SourceConfig Pydantic model."""

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


# ============================================================================
# SynchronizerConfig Tests
# ============================================================================


class TestSynchronizerConfig:
    """Tests for SynchronizerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SynchronizerConfig()

        assert config.tor.enabled is True
        assert config.filter.limit == 500
        assert config.time_range.default_start == 0
        assert config.timeouts.clearnet.request == 30.0
        assert config.concurrency.max_parallel == 10
        assert config.source.from_database is True
        assert config.interval == 900.0

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = SynchronizerConfig(
            tor=TorConfig(enabled=False),
            concurrency=ConcurrencyConfig(max_parallel=5),
            interval=1800.0,
        )

        assert config.tor.enabled is False
        assert config.concurrency.max_parallel == 5
        assert config.interval == 1800.0


# ============================================================================
# Synchronizer Initialization Tests
# ============================================================================


class TestSynchronizerInit:
    """Tests for Synchronizer initialization."""

    def test_init_with_defaults(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test initialization with defaults."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        assert sync._brotr is mock_synchronizer_brotr
        assert sync.SERVICE_NAME == "synchronizer"
        assert sync.config.tor.enabled is True

    def test_init_with_custom_config(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = SynchronizerConfig(
            tor=TorConfig(enabled=False),
            concurrency=ConcurrencyConfig(max_parallel=5),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        assert sync.config.tor.enabled is False
        assert sync.config.concurrency.max_parallel == 5

    def test_from_dict(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "tor": {"enabled": False},
            "concurrency": {"max_parallel": 5},
        }
        sync = Synchronizer.from_dict(data, brotr=mock_synchronizer_brotr)

        assert sync.config.tor.enabled is False
        assert sync.config.concurrency.max_parallel == 5


# ============================================================================
# Synchronizer Fetch Relays Tests
# ============================================================================


class TestSynchronizerFetchRelays:
    """Tests for Synchronizer._fetch_relays() method."""

    @pytest.mark.asyncio
    async def test_fetch_relays_empty(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when none available."""
        mock_synchronizer_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync._fetch_relays()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_disabled(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays when source is disabled."""
        config = SynchronizerConfig(source=SourceConfig(from_database=False))
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relays = await sync._fetch_relays()

        assert relays == []

    @pytest.mark.asyncio
    async def test_fetch_relays_with_results(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays from database."""
        mock_synchronizer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://relay1.example.com"},
                {"relay_url": "wss://relay2.example.com"},
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync._fetch_relays()

        assert len(relays) == 2
        assert "relay1.example.com" in relays[0].url
        assert "relay2.example.com" in relays[1].url

    @pytest.mark.asyncio
    async def test_fetch_relays_filters_invalid(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test fetching relays filters invalid URLs."""
        mock_synchronizer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"relay_url": "wss://valid.relay.com"},
                {"relay_url": "invalid-url"},
            ]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync._fetch_relays()

        assert len(relays) == 1
        assert "valid.relay.com" in relays[0].url


# ============================================================================
# Synchronizer Get Start Time Tests
# ============================================================================


class TestSynchronizerGetStartTime:
    """Tests for Synchronizer._get_start_time() method."""

    @pytest.mark.asyncio
    async def test_get_start_time_default(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test get start time with default."""
        mock_synchronizer_brotr.pool._mock_connection.fetchrow = AsyncMock(return_value=None)  # type: ignore[attr-defined]

        config = SynchronizerConfig(
            time_range=TimeRangeConfig(default_start=1000, use_relay_state=False)
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://test.relay.com")
        start_time = await sync._get_start_time(relay)

        assert start_time == 1000

    @pytest.mark.asyncio
    async def test_get_start_time_from_database(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test get start time from database."""
        mock_synchronizer_brotr.pool._mock_connection.fetchrow = AsyncMock(  # type: ignore[attr-defined]
            return_value={"max_created_at": 12000}
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relay = Relay("wss://test.relay.com")
        start_time = await sync._get_start_time(relay)

        assert start_time == 12001  # max_created_at + 1

    @pytest.mark.asyncio
    async def test_get_start_time_no_events(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test get start time when no events exist."""
        mock_synchronizer_brotr.pool._mock_connection.fetchrow = AsyncMock(  # type: ignore[attr-defined]
            return_value={"max_created_at": None}
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relay = Relay("wss://test.relay.com")
        start_time = await sync._get_start_time(relay)

        assert start_time == 0  # default_start


# ============================================================================
# Synchronizer Run Tests
# ============================================================================


class TestSynchronizerRun:
    """Tests for Synchronizer.run() method."""

    @pytest.mark.asyncio
    async def test_run_no_relays(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run cycle with no relays."""
        mock_synchronizer_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        await sync.run()

        assert sync._synced_relays == 0
        assert sync._synced_events == 0


# ============================================================================
# _create_filter Tests
# ============================================================================


class TestCreateFilter:
    """Tests for _create_filter helper function."""

    def test_create_filter_basic(self) -> None:
        """Test creating basic filter."""
        filter_config = FilterConfig()
        filter_obj = _create_filter(since=100, until=200, config=filter_config)

        assert filter_obj.since == 100
        assert filter_obj.until == 200
        assert filter_obj.limit == 500

    def test_create_filter_with_config(self) -> None:
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


# ============================================================================
# RawEventBatch Tests
# ============================================================================


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

        batch.append("not a dict")  # type: ignore[arg-type]
        batch.append(123)  # type: ignore[arg-type]
        batch.append(None)  # type: ignore[arg-type]

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

