"""Unit tests for the synchronizer service package."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Filter, NostrSdkError

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.brotr import TimeoutsConfig as BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.services.synchronizer import (
    ProcessingConfig,
    Synchronizer,
    SynchronizerConfig,
    TimeoutsConfig,
)
from bigbrotr.services.synchronizer.queries import (
    delete_stale_cursors,
    fetch_cursors_to_sync,
    insert_event_relays,
    upsert_sync_cursors,
)


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture(autouse=True)
def set_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", VALID_HEX_KEY)


@pytest.fixture
def mock_synchronizer_brotr(mock_brotr: Brotr) -> Brotr:
    mock_batch_config = MagicMock()
    mock_batch_config.max_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = BrotrTimeoutsConfig()
    mock_brotr._config = mock_config
    mock_brotr.insert_event_relay = AsyncMock(return_value=0)  # type: ignore[attr-defined]
    mock_brotr.upsert_service_state = AsyncMock(return_value=0)  # type: ignore[attr-defined]
    return mock_brotr


@pytest.fixture
def query_brotr() -> MagicMock:
    brotr = MagicMock()
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.fetch = AsyncMock(return_value=[])
    brotr.insert_event_relay = AsyncMock(return_value=0)
    brotr.upsert_service_state = AsyncMock(return_value=None)
    brotr.config.batch.max_size = 1000
    return brotr


_mock_event_counter = 0


def _make_mock_event(created_at_secs: int) -> MagicMock:
    global _mock_event_counter  # noqa: PLW0603
    _mock_event_counter += 1
    event = MagicMock()
    mock_timestamp = MagicMock()
    mock_timestamp.as_secs.return_value = created_at_secs
    event.created_at.return_value = mock_timestamp
    event.id.return_value.to_hex.return_value = f"{_mock_event_counter:064x}"
    return event


# ============================================================================
# Configs
# ============================================================================


class TestFilterParsing:
    def test_default_empty_filter(self) -> None:
        config = ProcessingConfig()
        assert len(config.filters) == 1
        assert isinstance(config.filters[0], Filter)

    def test_kinds_filter(self) -> None:
        config = ProcessingConfig(filters=[{"kinds": [1, 3, 30023]}])
        assert len(config.filters) == 1
        assert isinstance(config.filters[0], Filter)

    def test_authors_filter(self) -> None:
        config = ProcessingConfig(filters=[{"authors": ["a" * 64]}])
        assert isinstance(config.filters[0], Filter)

    def test_tag_filter(self) -> None:
        config = ProcessingConfig(filters=[{"#e": ["b" * 64]}])
        assert isinstance(config.filters[0], Filter)

    def test_multiple_filters(self) -> None:
        config = ProcessingConfig(filters=[{"kinds": [1]}, {"kinds": [2]}])
        assert len(config.filters) == 2

    def test_temporal_fields_accepted(self) -> None:
        config = ProcessingConfig(filters=[{"kinds": [1], "since": 100, "until": 200, "limit": 50}])
        assert isinstance(config.filters[0], Filter)

    def test_invalid_authors_hex_raises(self) -> None:
        with pytest.raises(ValueError, match="filters"):
            ProcessingConfig(filters=[{"authors": ["zz"]}])

    def test_non_dict_raises(self) -> None:
        with pytest.raises(TypeError, match="expected dict"):
            ProcessingConfig(filters=["not a dict"])

    def test_non_list_raises(self) -> None:
        with pytest.raises(TypeError, match="expected list"):
            ProcessingConfig(filters="not a list")  # type: ignore[arg-type]

    def test_filter_passthrough(self) -> None:
        from nostr_sdk import Kind

        f = Filter().kinds([Kind(1)])
        config = ProcessingConfig(filters=[f])
        assert config.filters[0] is f


class TestTimeoutsConfig:
    def test_default_values(self) -> None:
        config = TimeoutsConfig()

        assert config.relay_clearnet == 1800.0
        assert config.relay_tor == 3600.0
        assert config.relay_i2p == 3600.0
        assert config.relay_loki == 3600.0
        assert config.max_duration == 14_400.0

    def test_get_relay_timeout_defaults(self) -> None:
        config = TimeoutsConfig()

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 1800.0
        assert config.get_relay_timeout(NetworkType.TOR) == 3600.0
        assert config.get_relay_timeout(NetworkType.I2P) == 3600.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 3600.0

    def test_get_relay_timeout_custom_values(self) -> None:
        config = TimeoutsConfig(
            relay_clearnet=500.0,
            relay_tor=1800.0,
            relay_i2p=2000.0,
            relay_loki=2500.0,
        )

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 500.0
        assert config.get_relay_timeout(NetworkType.TOR) == 1800.0
        assert config.get_relay_timeout(NetworkType.I2P) == 2000.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 2500.0

    def test_custom_relay_values(self) -> None:
        config = TimeoutsConfig(
            relay_clearnet=900.0,
            relay_tor=1800.0,
        )

        assert config.relay_clearnet == 900.0
        assert config.relay_tor == 1800.0

    def test_max_duration_valid(self) -> None:
        config = TimeoutsConfig(max_duration=3600.0)

        assert config.max_duration == 3600.0

    def test_max_duration_at_min_relay_timeout(self) -> None:
        config = TimeoutsConfig(
            relay_clearnet=60.0,
            relay_tor=60.0,
            relay_i2p=60.0,
            relay_loki=60.0,
            max_duration=60.0,
        )

        assert config.max_duration == 60.0

    def test_max_duration_below_minimum_raises(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 60"):
            TimeoutsConfig(max_duration=1.0)

    def test_max_duration_below_shortest_relay_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= the shortest relay timeout"):
            TimeoutsConfig(max_duration=60.0)

    def test_max_duration_above_upper_bound_raises(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 86400"):
            TimeoutsConfig(max_duration=100_000.0)


class TestSynchronizerConfig:
    def test_default_values(self) -> None:
        config = SynchronizerConfig()

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False
        assert config.processing.since == 0
        assert config.processing.until is None
        assert config.processing.limit == 500
        assert config.processing.end_lag == 86_400
        assert config.networks.clearnet.timeout == 10.0
        assert config.timeouts.relay_clearnet == 1800.0
        assert config.processing.batch_size == 1000
        assert config.processing.allow_insecure is False
        assert config.interval == 300.0

    def test_get_end_time_default(self) -> None:
        config = ProcessingConfig()
        end = config.get_end_time()

        assert abs(end - (int(time.time()) - 86_400)) <= 2

    def test_get_end_time_with_until(self) -> None:
        config = ProcessingConfig(until=1_000_000, end_lag=3600)
        assert config.get_end_time() == 1_000_000 - 3600

    def test_until_minus_lag_below_since_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= since"):
            ProcessingConfig(since=1000, until=1500, end_lag=600)

    def test_until_minus_lag_equals_since_ok(self) -> None:
        config = ProcessingConfig(since=1000, until=2000, end_lag=1000)
        assert config.get_end_time() == 1000

    def test_custom_nested_config(self) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            interval=1800.0,
        )

        assert config.networks.tor.enabled is True
        assert config.interval == 1800.0


# ============================================================================
# Queries
# ============================================================================


class TestDeleteStaleCursors:
    async def test_calls_fetchval_with_correct_params(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=5)

        result = await delete_stale_cursors(query_brotr)

        query_brotr.fetchval.assert_awaited_once()
        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "NOT EXISTS" in sql
        assert args[0][1] == ServiceName.SYNCHRONIZER
        assert args[0][2] == ServiceStateType.CURSOR
        assert result == 5


class TestInsertEventRelays:
    async def test_delegates_to_insert_event_relay(self, query_brotr: MagicMock) -> None:
        query_brotr.insert_event_relay = AsyncMock(return_value=3)

        result = await insert_event_relays(query_brotr, [MagicMock(), MagicMock(), MagicMock()])

        assert result == 3
        query_brotr.insert_event_relay.assert_awaited_once()

    async def test_empty_returns_zero(self, query_brotr: MagicMock) -> None:
        result = await insert_event_relays(query_brotr, [])

        assert result == 0
        query_brotr.insert_event_relay.assert_not_awaited()

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        query_brotr.insert_event_relay = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await insert_event_relays(query_brotr, records)

        assert result == 6  # 2 + 2 + 2
        assert query_brotr.insert_event_relay.await_count == 3


class TestFetchCursorsToSync:
    async def test_returns_empty_for_no_rows(self, query_brotr: MagicMock) -> None:
        result = await fetch_cursors_to_sync(query_brotr, 1000, [NetworkType.CLEARNET])

        assert result == []

    async def test_returns_cursors_with_state(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                {
                    "url": "wss://relay1.example.com",
                    "state_value": {"timestamp": 500, "id": "aa" * 32},
                },
                {
                    "url": "wss://relay2.example.com",
                    "state_value": None,
                },
            ]
        )

        result = await fetch_cursors_to_sync(query_brotr, 1000, [NetworkType.CLEARNET])

        assert len(result) == 2
        assert result[0].key == "wss://relay1.example.com"
        assert result[0].timestamp == 500
        assert result[0].id == "aa" * 32
        assert result[1].key == "wss://relay2.example.com"
        assert result[1].timestamp == 0
        assert result[1].id == "0" * 64

    async def test_passes_correct_sql_params(self, query_brotr: MagicMock) -> None:
        await fetch_cursors_to_sync(query_brotr, 5000, [NetworkType.CLEARNET, NetworkType.TOR])

        args = query_brotr.fetch.call_args[0]
        assert "LEFT JOIN" in args[0]
        assert args[1] == ServiceName.SYNCHRONIZER
        assert args[2] == ServiceStateType.CURSOR
        assert args[3] == 5000
        assert args[4] == ["clearnet", "tor"]


class TestUpsertSyncCursors:
    async def test_upserts_multiple_cursors(self, query_brotr: MagicMock) -> None:
        cursors = [
            SyncCursor(key="wss://relay1.example.com", timestamp=100, id="ff" * 32),
            SyncCursor(key="wss://relay2.example.com", timestamp=200, id="ab" * 32),
        ]
        await upsert_sync_cursors(query_brotr, cursors)

        query_brotr.upsert_service_state.assert_awaited_once()
        states = query_brotr.upsert_service_state.call_args[0][0]
        assert len(states) == 2
        assert states[0].state_key == "wss://relay1.example.com"
        assert states[0].state_value["timestamp"] == 100
        assert states[0].state_value["id"] == "ff" * 32
        assert states[1].state_key == "wss://relay2.example.com"
        assert states[1].state_value["timestamp"] == 200

    async def test_empty_list_is_noop(self, query_brotr: MagicMock) -> None:
        await upsert_sync_cursors(query_brotr, [])

        query_brotr.upsert_service_state.assert_not_awaited()

    async def test_default_cursor_stores_defaults(self, query_brotr: MagicMock) -> None:
        cursor = SyncCursor(key="wss://relay.example.com")
        await upsert_sync_cursors(query_brotr, [cursor])

        states = query_brotr.upsert_service_state.call_args[0][0]
        assert states[0].state_value == {"timestamp": 0, "id": "0" * 64}

    async def test_splits_large_batch(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        cursors = [
            SyncCursor(key=f"wss://relay{i}.example.com", timestamp=i * 100, id=f"{i:064x}")
            for i in range(5)
        ]
        await upsert_sync_cursors(query_brotr, cursors)

        assert query_brotr.upsert_service_state.await_count == 3


# ============================================================================
# Service
# ============================================================================


class TestSynchronizerInit:
    def test_init_with_defaults(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        assert sync._brotr is mock_synchronizer_brotr
        assert sync.SERVICE_NAME == "synchronizer"
        assert sync.config.networks.clearnet.enabled is True
        assert sync.config.networks.tor.enabled is False

    def test_init_with_custom_config(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        assert sync.config.networks.tor.enabled is True

    def test_from_dict(self, mock_synchronizer_brotr: Brotr) -> None:
        data = {
            "networks": {"tor": {"enabled": True}},
        }
        sync = Synchronizer.from_dict(data, brotr=mock_synchronizer_brotr)

        assert sync.config.networks.tor.enabled is True


class TestSynchronizerRun:
    async def test_run_delegates_to_synchronize(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.synchronize = AsyncMock(return_value=0)  # type: ignore[method-assign]

        await sync.run()

        sync.synchronize.assert_awaited_once()


# ============================================================================
# Synchronize
# ============================================================================


class TestSynchronize:
    async def test_returns_zero_when_no_networks_enabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(clearnet=ClearnetConfig(enabled=False)),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        result = await sync.synchronize()

        assert result == 0

    async def test_returns_zero_when_no_cursors(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        with patch(
            "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await sync.synchronize()

        assert result == 0

    async def test_aggregates_events_from_workers(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        evt1 = _make_mock_event(100)
        evt2 = _make_mock_event(200)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1, relay
            yield evt2, relay

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            result = await sync.synchronize()

        assert result == 2
        sync.set_gauge.assert_any_call("relays_seen", 1)
        sync.set_gauge.assert_any_call("events_seen", 2)

    async def test_worker_exception_does_not_raise(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://failing.relay.com")

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def failing_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise RuntimeError("unexpected")
            yield  # make it a generator  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch.object(sync, "_sync_worker", side_effect=failing_worker),
        ):
            result = await sync.synchronize()

        assert result == 0

    async def test_cursor_save_error_propagates(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        evt1 = _make_mock_event(100)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1, relay

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db error"),
            ),
            pytest.raises(RuntimeError, match="db error"),
        ):
            await sync.synchronize()

    async def test_flushes_at_batch_size(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        events = [_make_mock_event(i * 100) for i in range(3)]

        config = SynchronizerConfig(processing=ProcessingConfig(batch_size=2))
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            for evt in events:
                yield evt, relay

        mock_insert = AsyncMock(side_effect=[2, 1])
        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                mock_insert,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            result = await sync.synchronize()

        assert result == 3
        assert mock_insert.await_count == 2

    async def test_max_duration_exceeded_breaks_after_flush(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        events = [_make_mock_event(i * 100) for i in range(4)]

        config = SynchronizerConfig(
            processing=ProcessingConfig(batch_size=2),
            timeouts=TimeoutsConfig(max_duration=1800.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            for evt in events:
                yield evt, relay

        original_monotonic = time.monotonic
        call_count = 0

        def mock_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return original_monotonic() + 7200
            return original_monotonic()

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.time.monotonic", side_effect=mock_monotonic
            ),
        ):
            result = await sync.synchronize()

        assert result == 2

    async def test_emits_total_relays_and_relays_seen_gauges(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        evt1 = _make_mock_event(100)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1, relay

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            await sync.synchronize()

        sync.set_gauge.assert_any_call("total_relays", 1)
        sync.set_gauge.assert_any_call("relays_seen", 1)

    async def test_events_seen_gauge_incremented(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        relay = Relay("wss://relay1.example.com")
        evt1 = _make_mock_event(100)
        evt2 = _make_mock_event(200)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_worker(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1, relay
            yield evt2, relay

        with (
            patch(
                "bigbrotr.services.synchronizer.service.fetch_cursors_to_sync",
                new_callable=AsyncMock,
                return_value=[cursor],
            ),
            patch("bigbrotr.services.synchronizer.service.EventRelay"),
            patch(
                "bigbrotr.services.synchronizer.service.insert_event_relays",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(sync, "_sync_worker", side_effect=fake_sync_worker),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            await sync.synchronize()

        sync.set_gauge.assert_any_call("events_seen", 1)
        sync.set_gauge.assert_any_call("events_seen", 2)


# ============================================================================
# _sync_worker
# ============================================================================


class TestSyncWorker:
    async def test_unknown_network_yields_nothing(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.network_semaphores = {}

        cursor = SyncCursor(key="wss://unknown.relay.com")
        items = [item async for item in sync._sync_worker(cursor)]

        assert items == []

    async def test_shutdown_before_connect_yields_nothing(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.request_shutdown()

        cursor = SyncCursor(key="wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.connect_relay",
            new_callable=AsyncMock,
        ) as mock_connect:
            items = [item async for item in sync._sync_worker(cursor)]

        assert items == []
        mock_connect.assert_not_awaited()

    @pytest.mark.parametrize(
        "error",
        [OSError("connection refused"), TimeoutError("timed out")],
        ids=["os_error", "timeout_error"],
    )
    async def test_connect_failure_yields_nothing(
        self, mock_synchronizer_brotr: Brotr, error: Exception
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        cursor = SyncCursor(key="wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.connect_relay",
            new_callable=AsyncMock,
            side_effect=error,
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        assert items == []

    async def test_yields_events_and_disconnects(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(processing=ProcessingConfig(limit=2))
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()

        evt_a = _make_mock_event(100)
        evt_b = _make_mock_event(200)

        async def fake_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt_a
            yield evt_b

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=fake_stream,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        assert len(items) == 2
        assert items[0][0] is evt_a
        assert items[1][0] is evt_b
        mock_client.disconnect.assert_awaited_once()

    async def test_empty_stream_disconnects_normally(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()

        async def empty_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            return
            yield  # make it a generator  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=empty_stream,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        assert items == []
        mock_client.disconnect.assert_awaited_once()

    @pytest.mark.parametrize(
        "error",
        [
            OSError("connection lost"),
            TimeoutError("timed out"),
            NostrSdkError("sdk error"),
        ],
        ids=["os_error", "timeout_error", "nostr_sdk_error"],
    )
    async def test_stream_error_yields_nothing(
        self, mock_synchronizer_brotr: Brotr, error: Exception
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.shutdown = AsyncMock()

        async def error_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise error
            yield  # make it a generator  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=error_stream,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        assert items == []

    async def test_client_shutdown_error_handled(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock(side_effect=RuntimeError("FFI crash"))

        async def empty_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            return
            yield  # make it a generator  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=empty_stream,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        mock_client.shutdown.assert_awaited_once()
        assert items == []

    async def test_relay_deadline_exceeded(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(relay_clearnet=60.0, max_duration=14_400.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.shutdown = AsyncMock()

        evt_a = _make_mock_event(100)
        evt_b = _make_mock_event(200)

        original_monotonic = time.monotonic
        call_count = 0

        def mock_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # First call: deadline = monotonic() + 60
            # Second call (after first yield): return past deadline
            if call_count >= 2:
                return original_monotonic() + 3600
            return original_monotonic()

        async def fake_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt_a
            yield evt_b

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=fake_stream,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.time.monotonic",
                side_effect=mock_monotonic,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        # Only first event yielded; second was skipped due to deadline
        assert len(items) == 1
        assert items[0][0] is evt_a

    async def test_outer_exception_boundary(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.shutdown = AsyncMock()

        async def exploding_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise RuntimeError("unexpected failure")
            yield  # make it a generator  # pragma: no cover

        with (
            patch(
                "bigbrotr.services.synchronizer.service.connect_relay",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.stream_events",
                side_effect=exploding_stream,
            ),
        ):
            items = [item async for item in sync._sync_worker(cursor)]

        assert items == []


# ============================================================================
# Cleanup
# ============================================================================


class TestSynchronizerCleanup:
    async def test_cleanup_removes_orphaned_cursors(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr.fetchval = AsyncMock(return_value=3)
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        result = await sync.cleanup()
        mock_synchronizer_brotr.fetchval.assert_awaited_once()
        sql = mock_synchronizer_brotr.fetchval.call_args[0][0]
        assert "NOT EXISTS" in sql
        assert result == 3
