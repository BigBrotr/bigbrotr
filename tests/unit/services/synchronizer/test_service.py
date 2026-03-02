"""
Unit tests for services.synchronizer.service module.

Tests:
- Synchronizer initialization and factory methods
- Relay fetching from database
- Cursor fetching and start time resolution from cache
- Run cycle orchestration and relay dispatch
- _run_sync structured concurrency (TaskGroup, semaphores,
  cursor flush, error handling, ExceptionGroup)
- Prometheus metric emission
- Network filtering
- Orphaned cursor cleanup
"""

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.configs import NetworksConfig, TorConfig
from bigbrotr.services.synchronizer import (
    ConcurrencyConfig,
    SourceConfig,
    Synchronizer,
    SynchronizerConfig,
    TimeoutsConfig,
    TimeRangeConfig,
)
from bigbrotr.services.synchronizer.utils import SyncBatchState


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
                    state_value={"timestamp": 1000},
                ),
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r2.com",
                    state_value={"timestamp": 2000},
                ),
            ]
        )
        result = await sync.fetch_cursors()

        mock_synchronizer_brotr.get_service_state.assert_awaited_once_with(
            ServiceName.SYNCHRONIZER, ServiceStateType.CURSOR
        )
        assert result == {
            "wss://r1.com": 1000,
            "wss://r2.com": 2000,
        }

    async def test_filters_cursors_with_missing_field(self, mock_synchronizer_brotr: Brotr) -> None:
        """Cursors missing timestamp are filtered out."""
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
                    state_value={"timestamp": 1000},
                ),
                ServiceState(
                    service_name=ServiceName.SYNCHRONIZER,
                    state_type=ServiceStateType.CURSOR,
                    state_key="wss://r2.com",
                    state_value={"stale_field": 999},
                ),
            ]
        )
        result = await sync.fetch_cursors()

        assert result == {
            "wss://r1.com": 1000,
        }


# ============================================================================
# Synchronizer Get Start Time Tests
# ============================================================================


class TestSynchronizerGetStartTime:
    """Tests for Synchronizer._get_start_time() method."""

    def test_returns_default_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test returns default_start when use_relay_state is False."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False, default_start=42),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time(
            relay,
            {"wss://relay.example.com": 1000},
        )
        assert result == 42

    def test_returns_cursor_plus_one_when_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns cursor + 1 when relay has a cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time(
            relay,
            {"wss://relay.example.com": 1000},
        )
        assert result == 1001

    def test_returns_default_when_cursor_not_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns default_start when relay has no cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=500),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://other.relay.com")

        result = sync._get_start_time(
            relay,
            {"wss://relay.example.com": 1000},
        )
        assert result == 500

    def test_returns_default_with_empty_cursors(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns default_start with empty cursor cache."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time(relay, {})
        assert result == 0


# ============================================================================
# Synchronizer Run Tests
# ============================================================================


class TestSynchronizerRun:
    """Tests for Synchronizer.run() method."""

    async def test_run_no_relays(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run cycle with no relays completes without error."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        await sync.run()

    async def test_run_with_relays_calls_run_sync(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() with relays fetches them and calls _run_sync."""
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
        sync._run_sync = AsyncMock(return_value=0)  # type: ignore[method-assign]
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        await sync.run()

        sync._run_sync.assert_called_once()
        relays_arg = sync._run_sync.call_args[0][0]
        assert len(relays_arg) == 1


# ============================================================================
# Synchronizer _run_sync Tests
# ============================================================================


class TestSynchronizerRunSync:
    """Tests for Synchronizer._run_sync() with TaskGroup."""

    async def test_run_sync_empty_list(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _run_sync with no relays returns zero events."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        result = await sync._run_sync([], {})

        assert result == 0

    async def test_run_sync_success_aggregates_results(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test successful sync aggregates events from all relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://success.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 2),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 10
        sync.set_gauge.assert_any_call("events_synced", 10)
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_run_sync_handles_task_group_errors(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that ExceptionGroup from TaskGroup is handled gracefully."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            side_effect=RuntimeError("unexpected"),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_timeout_counts_as_failure(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test TimeoutError from wait_for counts as scan failure."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://slow.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("overall timeout"),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_postgres_error_counts_as_failure(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test asyncpg.PostgresError counts as scan failure."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://db-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("db error"),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_os_error_counts_as_failure(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test OSError counts as scan failure."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://net-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_cursor_update_flushed(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test cursor updates are flushed at end of sync."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=50),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            await sync._run_sync([relay], {})

        mock_synchronizer_brotr.upsert_service_state.assert_called()

    async def test_run_sync_cursor_periodic_flush(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test cursor updates are periodically flushed when batch size reached."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(
                cursor_flush_interval=1,  # Flush after every relay
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relays = [
            Relay("wss://relay1.example.com"),
            Relay("wss://relay2.example.com"),
        ]

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            await sync._run_sync(relays, {})

        # Multiple calls: periodic flushes + final flush
        assert mock_synchronizer_brotr.upsert_service_state.call_count >= 2

    async def test_run_sync_final_cursor_flush_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test final cursor flush handles DB errors gracefully."""
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=999),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

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
            result = await sync._run_sync([relay], {})

        assert result == 1

    async def test_run_sync_skip_when_start_ge_end(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay is skipped when start_time >= end_time."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(
                default_start=999_999_999_999,  # Far future
                use_relay_state=False,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
        ) as mock_sync:
            await sync._run_sync([relay], {})

        mock_sync.assert_not_called()

    async def test_run_sync_with_cached_cursor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay uses cached cursor for start time."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
        cursors: dict[str, int] = {
            "wss://relay.example.com": 100,
        }

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ):
            result = await sync._run_sync([relay], cursors)

        assert result == 1


# ============================================================================
# Synchronizer Phase Timeout Tests
# ============================================================================


class TestSynchronizerPhaseTimeout:
    """Tests for max_duration phase-level timeout and is_running early exit."""

    async def test_max_duration_skips_relay(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay is skipped when max_duration is exceeded."""
        import asyncio
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=60.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        phase_start = time_mod.monotonic() - 61.0  # 61s ago → exceeds 60s limit
        batch = SyncBatchState(
            cursor_updates=[], cursor_lock=asyncio.Lock(), cursor_flush_interval=50
        )

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(5, 0),
        ) as mock_sync:
            result = await sync._sync_single_relay(relay, {}, batch, phase_start)

        assert result is None
        mock_sync.assert_not_called()

    async def test_max_duration_within_limit_proceeds(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay proceeds when max_duration is not exceeded."""
        import asyncio
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=3600.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        phase_start = time_mod.monotonic()  # Just started → within limit
        batch = SyncBatchState(
            cursor_updates=[], cursor_lock=asyncio.Lock(), cursor_flush_interval=50
        )

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 0),
        ):
            result = await sync._sync_single_relay(relay, {}, batch, phase_start)

        assert result == (10, 0)

    async def test_max_duration_none_allows_unlimited(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test max_duration=None does not limit sync phase."""
        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=None),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 0),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 10
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_max_duration_run_sync_integration(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test max_duration=60 via _run_sync skips relays when phase exceeded."""
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=60.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        original_monotonic = time_mod.monotonic

        call_count = 0

        def fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # First call: phase_start in _run_sync → return real time
            # Subsequent calls: return time far in the future to exceed max_duration
            if call_count == 1:
                return original_monotonic()
            return original_monotonic() + 61.0

        with (
            patch(
                "bigbrotr.services.synchronizer.service.sync_relay_events",
                new_callable=AsyncMock,
                return_value=(5, 0),
            ) as mock_sync,
            patch(
                "bigbrotr.services.synchronizer.service.time.monotonic", side_effect=fake_monotonic
            ),
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        mock_sync.assert_not_called()
        sync.set_gauge.assert_any_call("relays_scanned", 0)

    async def test_shutdown_skips_relay(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay is skipped when shutdown is requested."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]
        sync.request_shutdown()

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(5, 0),
        ) as mock_sync:
            result = await sync._run_sync([relay], {})

        assert result == 0
        mock_sync.assert_not_called()
        sync.set_gauge.assert_any_call("relays_scanned", 0)


# ============================================================================
# Synchronizer Metrics Tests
# ============================================================================


class TestSynchronizerMetrics:
    """Tests for Synchronizer Prometheus metric emission."""

    async def test_run_sync_emits_gauges(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _run_sync emits all progress gauges after synchronization."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay1.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(5, 1),
        ):
            await sync._run_sync([relay], {})

        sync.set_gauge.assert_any_call("events_synced", 5)
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_run_sync_emits_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test _run_sync emits cumulative counters after sync."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 2),
        ):
            await sync._run_sync([relay], {})

        sync.inc_counter.assert_any_call("total_events_synced", 10)
        sync.inc_counter.assert_any_call("total_events_invalid", 2)

    async def test_failed_relay_emits_sync_failures(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test failed relay emits total_sync_failures counter."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            await sync._run_sync([relay], {})

        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_failed_relay_no_event_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test failed relay does not contribute to event counters."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")

        with patch(
            "bigbrotr.services.synchronizer.service.sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            await sync._run_sync([relay], {})

        # Event counters should be called with 0 (no successful events)
        sync.inc_counter.assert_any_call("total_events_synced", 0)
        sync.inc_counter.assert_any_call("total_events_invalid", 0)

    async def test_synchronize_returns_events_synced(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test synchronize() returns total events synced."""
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
        sync._run_sync = AsyncMock(return_value=42)  # type: ignore[method-assign]
        sync.fetch_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        result = await sync.synchronize()

        assert result == 42

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
# Synchronizer Cleanup Tests
# ============================================================================


class TestSynchronizerCleanup:
    """Tests for cleanup() in Synchronizer."""

    async def test_cleanup_removes_orphaned_cursors(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        mock_synchronizer_brotr.fetchval = AsyncMock(return_value=3)
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        result = await sync.cleanup()
        mock_synchronizer_brotr.fetchval.assert_awaited_once()
        sql = mock_synchronizer_brotr.fetchval.call_args[0][0]
        assert "NOT EXISTS" in sql
        assert result == 3
