"""Unit tests for the synchronizer service package."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Filter

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.brotr import TimeoutsConfig as BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig, TorConfig
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.services.synchronizer import (
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
from bigbrotr.utils.streaming import _to_domain_events, stream_events


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
    event.author.return_value.to_hex.return_value = "b" * 64
    event.kind.return_value.as_u16.return_value = 1
    event.content.return_value = "test content"
    event.signature.return_value = "e" * 128
    event.verify.return_value = True

    mock_tags = []
    mock_tag = MagicMock()
    mock_tag.as_vec.return_value = ["e", "c" * 64]
    mock_tags.append(mock_tag)
    event.tags.return_value.to_vec.return_value = mock_tags

    return event


def _make_event_stream(events: list[MagicMock]) -> AsyncMock:
    iterator = iter([*events, None])
    stream = AsyncMock()
    stream.next = AsyncMock(side_effect=lambda: next(iterator))
    return stream


def _make_mock_filter() -> MagicMock:
    f = MagicMock(spec=Filter)
    f.since.return_value = f
    f.until.return_value = f
    f.limit.return_value = f
    f.match_event.return_value = True
    f.as_json.return_value = "{}"
    return f


# ============================================================================
# Configs
# ============================================================================


class TestFilterParsing:
    def test_default_empty_filter(self) -> None:
        config = SynchronizerConfig()
        assert len(config.filters) == 1
        assert isinstance(config.filters[0], Filter)

    def test_kinds_filter(self) -> None:
        config = SynchronizerConfig(filters=[{"kinds": [1, 3, 30023]}])
        assert len(config.filters) == 1
        assert isinstance(config.filters[0], Filter)

    def test_authors_filter(self) -> None:
        config = SynchronizerConfig(filters=[{"authors": ["a" * 64]}])
        assert isinstance(config.filters[0], Filter)

    def test_tag_filter(self) -> None:
        config = SynchronizerConfig(filters=[{"#e": ["b" * 64]}])
        assert isinstance(config.filters[0], Filter)

    def test_multiple_filters(self) -> None:
        config = SynchronizerConfig(filters=[{"kinds": [1]}, {"kinds": [2]}])
        assert len(config.filters) == 2

    def test_temporal_fields_accepted(self) -> None:
        config = SynchronizerConfig(
            filters=[{"kinds": [1], "since": 100, "until": 200, "limit": 50}]
        )
        assert isinstance(config.filters[0], Filter)

    def test_invalid_authors_hex_raises(self) -> None:
        with pytest.raises(ValueError, match="filters"):
            SynchronizerConfig(filters=[{"authors": ["zz"]}])

    def test_non_dict_raises(self) -> None:
        with pytest.raises(TypeError, match="expected dict"):
            SynchronizerConfig(filters=["not a dict"])

    def test_non_list_raises(self) -> None:
        with pytest.raises(TypeError, match="expected list"):
            SynchronizerConfig(filters="not a list")  # type: ignore[arg-type]

    def test_filter_passthrough(self) -> None:
        from nostr_sdk import Kind

        f = Filter().kinds([Kind(1)])
        config = SynchronizerConfig(filters=[f])
        assert config.filters[0] is f


class TestTimeoutsConfig:
    def test_default_values(self) -> None:
        config = TimeoutsConfig()

        assert config.relay_clearnet == 1800.0
        assert config.relay_tor == 3600.0
        assert config.relay_i2p == 3600.0
        assert config.relay_loki == 3600.0

    def test_get_relay_timeout(self) -> None:
        config = TimeoutsConfig()

        assert config.get_relay_timeout(NetworkType.CLEARNET) == 1800.0
        assert config.get_relay_timeout(NetworkType.TOR) == 3600.0
        assert config.get_relay_timeout(NetworkType.I2P) == 3600.0
        assert config.get_relay_timeout(NetworkType.LOKI) == 3600.0

    def test_custom_values(self) -> None:
        config = TimeoutsConfig(
            relay_clearnet=900.0,
            relay_tor=1800.0,
        )

        assert config.relay_clearnet == 900.0
        assert config.relay_tor == 1800.0

    def test_max_duration_default_none(self) -> None:
        config = TimeoutsConfig()

        assert config.max_duration is None

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
        assert config.since == 0
        assert config.until is None
        assert config.limit == 500
        assert config.end_lag == 86_400
        assert config.networks.clearnet.timeout == 10.0
        assert config.timeouts.relay_clearnet == 1800.0
        assert config.allow_insecure is False
        assert config.interval == 300.0

    def test_get_end_time_default(self) -> None:
        config = SynchronizerConfig()
        end = config.get_end_time()
        import time

        assert abs(end - (int(time.time()) - 86_400)) <= 2

    def test_get_end_time_with_until(self) -> None:
        config = SynchronizerConfig(until=1_000_000, end_lag=3600)
        assert config.get_end_time() == 1_000_000 - 3600

    def test_until_minus_lag_below_since_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >= since"):
            SynchronizerConfig(since=1000, until=1500, end_lag=600)

    def test_until_minus_lag_equals_since_ok(self) -> None:
        config = SynchronizerConfig(since=1000, until=2000, end_lag=1000)
        assert config.get_end_time() == 1000

    def test_custom_nested_config(self) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            interval=1800.0,
        )

        assert config.networks.tor.enabled is True
        assert config.interval == 1800.0

    def test_no_worker_log_level_field(self) -> None:
        assert not hasattr(SynchronizerConfig(), "worker_log_level")

    def test_no_flush_interval_field(self) -> None:
        assert not hasattr(SynchronizerConfig(), "flush_interval")


# ============================================================================
# Utils
# ============================================================================


class TestToDomainEvents:
    def test_sorts_ascending(self) -> None:
        evts = [_make_mock_event(300), _make_mock_event(100), _make_mock_event(200)]

        with patch("bigbrotr.utils.streaming.Event", side_effect=lambda x: x):
            result = _to_domain_events(evts)

        timestamps = [e.created_at().as_secs() for e in result]
        assert timestamps == [100, 200, 300]

    def test_empty_input(self) -> None:
        assert _to_domain_events([]) == []

    def test_parse_error_skipped(self) -> None:
        evts = [_make_mock_event(100), _make_mock_event(200)]

        call_count = 0

        def fail_second(x: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("null byte")
            return x

        with patch("bigbrotr.utils.streaming.Event", side_effect=fail_second):
            result = _to_domain_events(evts)

        assert len(result) == 1

    def test_type_error_skipped(self) -> None:
        evts = [_make_mock_event(100)]

        with patch("bigbrotr.utils.streaming.Event", side_effect=TypeError("bad")):
            result = _to_domain_events(evts)

        assert result == []

    def test_overflow_error_skipped(self) -> None:
        evts = [_make_mock_event(100)]

        with patch("bigbrotr.utils.streaming.Event", side_effect=OverflowError("overflow")):
            result = _to_domain_events(evts)

        assert result == []


class TestIterRelayEvents:
    @pytest.fixture(autouse=True)
    def _bypass_event_model(self) -> None:  # type: ignore[misc]
        """Patch Event constructor to passthrough so mock events survive conversion."""
        with patch("bigbrotr.utils.streaming.Event", side_effect=lambda x: x):
            yield

    async def test_empty_relay_yields_nothing(self) -> None:
        client = AsyncMock()
        client.stream_events = AsyncMock(return_value=_make_event_stream([]))
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0)]

        assert events == []

    async def test_single_window_under_limit(self) -> None:
        evt200 = _make_mock_event(200)
        evt300 = _make_mock_event(300)
        evt400 = _make_mock_event(400)
        # Main [100, 1000]: 3 events (under limit=500) → verify
        call1 = _make_event_stream([evt200, evt300, evt400])
        # Verify [100, 200]: event at min_ts=200
        call2 = _make_event_stream([evt200])
        # Probe [100, 199]: empty → complete
        call3 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0)]

        assert len(events) == 3
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_at_limit_smart_path_yields_combined(self) -> None:
        # Main fetch: 3 events (== limit), min_ts=120
        call1 = _make_event_stream(
            [_make_mock_event(120), _make_mock_event(160), _make_mock_event(180)]
        )
        # Verify fetch [100, 120]: events all at 120
        call2 = _make_event_stream([_make_mock_event(120)])
        # Probe [100, 119] with limit=1: empty → no events before 120
        call3 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 200, 3, 10.0)]

        # Should yield all events (combined from main + verify)
        assert len(events) >= 3
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_at_limit_inconsistent_verify_falls_back_to_binary_split(self) -> None:
        evt120 = _make_mock_event(120)
        evt180 = _make_mock_event(180)
        # Main fetch [100, 200]: 2 events (== limit), min_ts=120
        call1 = _make_event_stream([evt120, evt180])
        # Verify fetch [100, 120]: returns event at 110 (verify_max != min_ts) → inconsistent
        call2 = _make_event_stream([_make_mock_event(110)])
        # Binary split mid=150 → left half [100, 150]: 1 event at 120
        call3 = _make_event_stream([evt120])
        # Left verify [100, 120]: event at 120
        call4 = _make_event_stream([evt120])
        # Left probe [100, 119]: empty → complete
        call5 = _make_event_stream([])
        # Right half [151, 200]: 1 event at 180
        call6 = _make_event_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_event_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0)]

        assert len(events) == 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_at_limit_empty_verify_falls_back_to_binary_split(self) -> None:
        evt150 = _make_mock_event(150)
        evt180 = _make_mock_event(180)
        # Main fetch [100, 200]: 2 events (== limit)
        call1 = _make_event_stream([evt150, evt180])
        # Verify fetch: empty → inconsistent → fallback
        call2 = _make_event_stream([])
        # Binary split mid=150 → left [100, 150]: 1 event at 150
        call3 = _make_event_stream([evt150])
        # Left verify [100, 150]: event at 150
        call4 = _make_event_stream([evt150])
        # Left probe [100, 149]: empty → complete
        call5 = _make_event_stream([])
        # Right [151, 200]: 1 event at 180
        call6 = _make_event_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_event_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0)]

        assert len(events) == 2

    async def test_single_second_window_yields_all(self) -> None:
        evts = [_make_mock_event(500), _make_mock_event(500), _make_mock_event(500)]
        client = AsyncMock()
        client.stream_events = AsyncMock(return_value=_make_event_stream(evts))
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 500, 500, 3, 10.0)]

        assert len(events) == 3

    async def test_exception_propagates(self) -> None:
        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=TimeoutError("fetch timeout"))
        filters = [_make_mock_filter()]

        with pytest.raises(TimeoutError, match="fetch timeout"):
            async for _ in stream_events(client, filters, 100, 1000, 500, 10.0):
                pass

    async def test_ascending_order_within_window(self) -> None:
        # Events in reverse order — should be sorted ascending on yield
        evt200 = _make_mock_event(200)
        evt300 = _make_mock_event(300)
        evt400 = _make_mock_event(400)
        # Main [100, 1000]: sorted by _fetch_validated to [200, 300, 400]
        call1 = _make_event_stream([evt400, evt200, evt300])
        # Verify [100, 200]: event at min_ts=200
        call2 = _make_event_stream([evt200])
        # Probe [100, 199]: empty → complete
        call3 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0)]

        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == [200, 300, 400]

    async def test_multiple_filters_deduplicates(self) -> None:
        # Same events returned by both filters — should be deduplicated
        evt200 = _make_mock_event(200)
        evt300 = _make_mock_event(300)

        # Main fetch: filter1 → [200, 300], filter2 → [200, 300] (deduped)
        s1 = _make_event_stream([evt200, evt300])
        s2 = _make_event_stream([evt200, evt300])
        # Verify [100, 200]: filter1 → [200], filter2 → [200] (deduped)
        s3 = _make_event_stream([evt200])
        s4 = _make_event_stream([evt200])
        # Probe [100, 199]: filter1 → empty, filter2 → empty
        s5 = _make_event_stream([])
        s6 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[s1, s2, s3, s4, s5, s6])
        filters = [_make_mock_filter(), _make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0)]

        # Each event appears once despite two filters returning same events
        assert len(events) == 2

    async def test_partial_completion_on_exception(self) -> None:
        evt200 = _make_mock_event(200)
        # [100, 1000] limit=2: 2 events → at limit → smart verify
        call1 = _make_event_stream([evt200, _make_mock_event(800)])
        # Verify empty → inconsistent → binary split mid=550
        call2 = _make_event_stream([])
        # Left half [100, 550]: 1 event at 200
        call3 = _make_event_stream([evt200])
        # Left verify [100, 200]: event at 200
        call4 = _make_event_stream([evt200])
        # Left probe [100, 199]: empty → complete → yield
        call5 = _make_event_stream([])
        # Right half [551, 1000]: raises
        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, OSError("connection lost")]
        )
        filters = [_make_mock_filter()]

        events: list[MagicMock] = []
        with pytest.raises(OSError, match="connection lost"):
            async for e in stream_events(client, filters, 100, 1000, 2, 10.0):
                events.append(e)

        # First event yielded before the error on the right half
        assert len(events) == 1

    async def test_verify_min_differs_triggers_split(self) -> None:
        evt130 = _make_mock_event(130)
        evt180 = _make_mock_event(180)
        # Main fetch [100, 200]: 2 events (== limit), min_ts=150
        call1 = _make_event_stream([_make_mock_event(150), evt180])
        # Verify [100, 150]: returns event at ts=130 (verify_min=130 != min_ts=150)
        # → earlier events exist → split
        call2 = _make_event_stream([evt130, _make_mock_event(150)])
        # Binary split mid=150 → left [100, 150]: 1 event at 130
        call3 = _make_event_stream([evt130])
        # Left verify [100, 130]: event at 130
        call4 = _make_event_stream([evt130])
        # Left probe [100, 129]: empty → complete
        call5 = _make_event_stream([])
        # Right [151, 200]: 1 event at 180
        call6 = _make_event_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_event_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0)]

        assert len(events) == 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_probe_finds_events_triggers_split(self) -> None:
        evt120 = _make_mock_event(120)
        evt150 = _make_mock_event(150)
        evt280 = _make_mock_event(280)
        # Main fetch [100, 300]: 3 events (== limit), min_ts=150
        call1 = _make_event_stream([evt150, _make_mock_event(200), evt280])
        # Verify [100, 150]: all at 150
        call2 = _make_event_stream([evt150])
        # Probe [100, 149] limit=1: finds event → earlier data exists → split
        call3 = _make_event_stream([evt120])
        # Binary split mid=200 → left [100, 200]: 2 events at 120, 150
        call4 = _make_event_stream([evt120, evt150])
        # Left verify [100, 120]: event at 120
        call5 = _make_event_stream([evt120])
        # Left probe [100, 119]: empty → complete
        call6 = _make_event_stream([])
        # Right [201, 300]: 1 event at 280
        call7 = _make_event_stream([evt280])
        # Right verify [201, 280]: event at 280
        call8 = _make_event_stream([evt280])
        # Right probe [201, 279]: empty → complete
        call9 = _make_event_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8, call9]
        )
        filters = [_make_mock_filter()]

        events = [e async for e in stream_events(client, filters, 100, 300, 3, 10.0)]

        assert len(events) >= 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)


class TestTimeoutsConfigGetRelayTimeout:
    def test_get_relay_timeout_clearnet_explicit(self) -> None:
        config = TimeoutsConfig(relay_clearnet=500.0)
        assert config.get_relay_timeout(NetworkType.CLEARNET) == 500.0

    def test_get_relay_timeout_i2p(self) -> None:
        config = TimeoutsConfig(relay_i2p=2000.0)
        assert config.get_relay_timeout(NetworkType.I2P) == 2000.0

    def test_get_relay_timeout_loki(self) -> None:
        config = TimeoutsConfig(relay_loki=2500.0)
        assert config.get_relay_timeout(NetworkType.LOKI) == 2500.0


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
        evt1 = _make_mock_event(100)
        evt2 = _make_mock_event(200)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1
            yield evt2

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
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
            patch.object(sync, "_sync_relay_events", side_effect=failing_worker),
        ):
            result = await sync.synchronize()

        assert result == 0

    async def test_cursor_save_error_propagates(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        evt1 = _make_mock_event(100)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db error"),
            ),
            pytest.raises(RuntimeError, match="db error"),
        ):
            await sync.synchronize()

    async def test_flushes_at_batch_size(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr._config.batch.max_size = 2
        cursor = SyncCursor(key="wss://relay1.example.com")
        events = [_make_mock_event(i * 100) for i in range(3)]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            for evt in events:
                yield evt

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            result = await sync.synchronize()

        assert result == 3
        assert mock_insert.await_count == 2


# ============================================================================
# _sync_relay_events
# ============================================================================


class TestSyncRelayEvents:
    async def test_unknown_network_yields_nothing(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = MagicMock(spec=Relay)
        relay.url = "wss://unknown.relay.com"
        relay.network = MagicMock()
        relay.network.value = "unknown_net"

        cursor = SyncCursor(key="wss://unknown.relay.com")
        items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert items == []

    async def test_start_ge_end_yields_nothing(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(since=0, until=100, end_lag=0)
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key="wss://relay.example.com", timestamp=100, id="ff" * 32)

        with patch(
            "bigbrotr.services.synchronizer.service.connect_relay",
            new_callable=AsyncMock,
        ) as mock_connect:
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert items == []
        mock_connect.assert_not_awaited()

    async def test_shutdown_before_connect_yields_nothing(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.request_shutdown()

        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key="wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.connect_relay",
            new_callable=AsyncMock,
        ) as mock_connect:
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert items == []
        mock_connect.assert_not_awaited()

    async def test_connect_failure_yields_nothing(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key="wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer.service.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert items == []

    async def test_yields_events(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(limit=2)
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()

        evt_a = MagicMock()
        ts_a = MagicMock()
        ts_a.as_secs.return_value = 100
        evt_a.created_at.return_value = ts_a

        evt_b = MagicMock()
        ts_b = MagicMock()
        ts_b.as_secs.return_value = 200
        evt_b.created_at.return_value = ts_b

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
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert len(items) == 2
        assert items[0] is evt_a
        assert items[1] is evt_b

    async def test_stream_error_yields_nothing(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
        cursor = SyncCursor(key="wss://relay.example.com")

        mock_client = AsyncMock()
        mock_client.shutdown = AsyncMock()

        async def error_stream(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise OSError("connection lost")
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
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        assert items == []

    async def test_client_shutdown_error_handled(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
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
            items = [item async for item in sync._sync_relay_events(relay, cursor)]

        mock_client.shutdown.assert_awaited_once()
        assert items == []


# ============================================================================
# Phase timeout via synchronize()
# ============================================================================


class TestSynchronizerPhaseTimeout:
    async def test_max_duration_none_allows_unlimited(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay.example.com")
        evt = _make_mock_event(100)

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=None),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            result = await sync.synchronize()

        assert result == 1
        sync.set_gauge.assert_any_call("relays_seen", 1)

    async def test_max_duration_exceeded_breaks_after_flush(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        mock_synchronizer_brotr._config.batch.max_size = 2
        cursor = SyncCursor(key="wss://relay1.example.com")
        events = [_make_mock_event(i * 100) for i in range(4)]

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=1800.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            for evt in events:
                yield evt

        # After first flush, monotonic() returns past the deadline
        original_monotonic = time.monotonic
        call_count = 0

        def mock_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # The deadline check is the call after flush; return a large value
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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
            patch(
                "bigbrotr.services.synchronizer.service.time.monotonic", side_effect=mock_monotonic
            ),
        ):
            result = await sync.synchronize()

        # Only first batch flushed, break before processing remaining events
        assert result == 2


# ============================================================================
# Metrics
# ============================================================================


class TestSynchronizerMetrics:
    async def test_emits_total_and_relays_seen_gauges(self, mock_synchronizer_brotr: Brotr) -> None:
        cursor = SyncCursor(key="wss://relay1.example.com")
        evt1 = _make_mock_event(100)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
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
        evt1 = _make_mock_event(100)
        evt2 = _make_mock_event(200)

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        async def fake_sync_relay_events(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            yield evt1
            yield evt2

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
            patch.object(sync, "_sync_relay_events", side_effect=fake_sync_relay_events),
            patch(
                "bigbrotr.services.synchronizer.service.upsert_sync_cursors",
                new_callable=AsyncMock,
            ),
        ):
            await sync.synchronize()

        sync.set_gauge.assert_any_call("events_seen", 1)
        sync.set_gauge.assert_any_call("events_seen", 2)


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
