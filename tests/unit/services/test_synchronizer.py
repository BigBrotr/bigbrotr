"""Unit tests for the synchronizer service package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.brotr import TimeoutsConfig as BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.configs import NetworksConfig, TorConfig
from bigbrotr.services.synchronizer import (
    ConcurrencyConfig,
    EventBatch,
    FilterConfig,
    Synchronizer,
    SynchronizerConfig,
    TimeoutsConfig,
    TimeRangeConfig,
)
from bigbrotr.services.synchronizer.queries import (
    delete_stale_cursors,
    insert_event_relays,
)
from bigbrotr.services.synchronizer.utils import (
    SyncBatchState,
    _log,
    create_filter,
    insert_batch,
    iter_relay_events,
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
    brotr.insert_event_relay = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


def _make_mock_event(created_at_secs: int) -> MagicMock:
    event = MagicMock()
    mock_timestamp = MagicMock()
    mock_timestamp.as_secs.return_value = created_at_secs
    event.created_at.return_value = mock_timestamp
    event.id.return_value.to_hex.return_value = "a" * 64
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


# ============================================================================
# Configs
# ============================================================================


class TestFilterConfig:
    def test_default_values(self) -> None:
        config = FilterConfig()

        assert config.ids is None
        assert config.kinds is None
        assert config.authors is None
        assert config.tags is None
        assert config.limit == 500

    def test_custom_values(self) -> None:
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
        config = FilterConfig(limit=1)
        assert config.limit == 1

        config = FilterConfig(limit=5000)
        assert config.limit == 5000

        with pytest.raises(ValueError):
            FilterConfig(limit=0)

        with pytest.raises(ValueError):
            FilterConfig(limit=5001)

    def test_kinds_validation_valid_range(self) -> None:
        config = FilterConfig(kinds=[0, 1, 30023, 65535])
        assert config.kinds == [0, 1, 30023, 65535]

    def test_kinds_validation_invalid_range(self) -> None:
        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[70000])

        with pytest.raises(ValueError, match="out of valid range"):
            FilterConfig(kinds=[-1])

    def test_ids_validation_valid_hex(self) -> None:
        valid_hex = "a" * 64
        config = FilterConfig(ids=[valid_hex])
        assert config.ids == [valid_hex]

    def test_ids_validation_invalid_length(self) -> None:
        with pytest.raises(ValueError, match="Invalid hex string length"):
            FilterConfig(ids=["short"])

    def test_authors_validation_valid_hex(self) -> None:
        valid_hex = "b" * 64
        config = FilterConfig(authors=[valid_hex])
        assert config.authors == [valid_hex]

    def test_authors_validation_invalid_hex_chars(self) -> None:
        with pytest.raises(ValueError, match="Invalid hex string"):
            FilterConfig(authors=["z" * 64])


class TestTimeRangeConfig:
    def test_default_values(self) -> None:
        config = TimeRangeConfig()

        assert config.default_start == 0
        assert config.use_relay_state is True
        assert config.lookback_seconds == 86400

    def test_custom_values(self) -> None:
        config = TimeRangeConfig(
            default_start=1000000,
            use_relay_state=False,
            lookback_seconds=3600,
        )

        assert config.default_start == 1000000
        assert config.use_relay_state is False
        assert config.lookback_seconds == 3600


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


class TestConcurrencyConfig:
    def test_default_values(self) -> None:
        config = ConcurrencyConfig()

        assert config.cursor_flush_interval == 50


class TestSynchronizerConfig:
    def test_default_values(self) -> None:
        config = SynchronizerConfig()

        assert config.networks.clearnet.enabled is True
        assert config.networks.tor.enabled is False  # disabled by default
        assert config.filter.limit == 500
        assert config.time_range.default_start == 0
        assert config.networks.clearnet.timeout == 10.0
        assert config.timeouts.relay_clearnet == 1800.0
        assert config.concurrency.cursor_flush_interval == 50
        assert config.interval == 300.0

    def test_custom_nested_config(self) -> None:
        config = SynchronizerConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True)),
            concurrency=ConcurrencyConfig(cursor_flush_interval=25),
            interval=1800.0,
        )

        assert config.networks.tor.enabled is True
        assert config.concurrency.cursor_flush_interval == 25
        assert config.interval == 1800.0

    def test_no_worker_log_level_field(self) -> None:
        assert not hasattr(SynchronizerConfig(), "worker_log_level")


# ============================================================================
# Utils
# ============================================================================


class TestLogUtility:
    def test_log_info_level(self) -> None:
        with patch("bigbrotr.services.synchronizer.utils._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            _log("INFO", "test_message", relay="wss://test.com", count=5)
            mock_logger.log.assert_called_once()
            args = mock_logger.log.call_args
            assert args[0][0] == 20  # logging.INFO
            assert "test_message" in args[0][1]

    def test_log_when_disabled(self) -> None:
        with patch("bigbrotr.services.synchronizer.utils._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = False
            _log("DEBUG", "should_not_log")
            mock_logger.log.assert_not_called()


class TestEventBatch:
    def test_init(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        assert batch.since == 100
        assert batch.until == 200
        assert batch.limit == 10
        assert batch.size == 0
        assert batch.events == []
        assert batch.min_created_at is None
        assert batch.max_created_at is None

    def test_append_valid_event(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        event = _make_mock_event(150)

        batch.append(event)

        assert batch.size == 1
        assert len(batch.events) == 1
        assert batch.min_created_at == 150
        assert batch.max_created_at == 150

    def test_append_multiple_events(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        for ts in [150, 120, 180]:
            event = _make_mock_event(ts)
            batch.append(event)

        assert batch.size == 3
        assert batch.min_created_at == 120
        assert batch.max_created_at == 180

    def test_append_rejects_out_of_bounds(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        # Event before since
        event1 = _make_mock_event(50)
        batch.append(event1)

        # Event after until
        event2 = _make_mock_event(250)
        batch.append(event2)

        assert batch.size == 0

    def test_append_accepts_boundary_values(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        event1 = _make_mock_event(100)
        batch.append(event1)

        event2 = _make_mock_event(200)
        batch.append(event2)

        assert batch.size == 2

    def test_append_raises_on_overflow(self) -> None:
        batch = EventBatch(since=100, until=200, limit=2)

        event1 = _make_mock_event(150)
        batch.append(event1)

        event2 = _make_mock_event(160)
        batch.append(event2)

        event3 = _make_mock_event(170)

        with pytest.raises(OverflowError, match="Batch limit reached"):
            batch.append(event3)

    def test_append_only_updates_min_when_smaller(self) -> None:
        batch = EventBatch(since=100, until=300, limit=10)

        batch.append(_make_mock_event(200))
        assert batch.min_created_at == 200
        assert batch.max_created_at == 200

        batch.append(_make_mock_event(250))
        assert batch.min_created_at == 200  # Unchanged
        assert batch.max_created_at == 250

        batch.append(_make_mock_event(150))
        assert batch.min_created_at == 150  # Updated
        assert batch.max_created_at == 250  # Unchanged

    def test_append_boundary_since_equals_until(self) -> None:
        batch = EventBatch(since=500, until=500, limit=10)

        evt = _make_mock_event(500)
        batch.append(evt)
        assert batch.size == 1

        # Outside range
        evt2 = _make_mock_event(499)
        batch.append(evt2)
        assert batch.size == 1

        evt3 = _make_mock_event(501)
        batch.append(evt3)
        assert batch.size == 1

    def test_is_full(self) -> None:
        batch = EventBatch(since=100, until=200, limit=2)

        assert batch.is_full() is False

        event1 = _make_mock_event(150)
        batch.append(event1)
        assert batch.is_full() is False

        event2 = _make_mock_event(160)
        batch.append(event2)
        assert batch.is_full() is True

    def test_is_full_at_limit_one(self) -> None:
        batch = EventBatch(since=100, until=200, limit=1)
        assert batch.is_full() is False

        batch.append(_make_mock_event(150))
        assert batch.is_full() is True

    def test_is_empty(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        assert batch.is_empty() is True

        event = _make_mock_event(150)
        batch.append(event)
        assert batch.is_empty() is False

    def test_len(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        assert len(batch) == 0

        event1 = _make_mock_event(150)
        batch.append(event1)

        event2 = _make_mock_event(160)
        batch.append(event2)

        assert len(batch) == 2

    def test_len_matches_size(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        assert len(batch) == batch.size == 0

        batch.append(_make_mock_event(150))
        assert len(batch) == batch.size == 1

        batch.append(_make_mock_event(160))
        assert len(batch) == batch.size == 2

    def test_iter(self) -> None:
        batch = EventBatch(since=100, until=200, limit=10)

        event1 = _make_mock_event(150)
        event2 = _make_mock_event(160)

        batch.append(event1)
        batch.append(event2)

        events = list(batch)
        assert len(events) == 2
        assert events[0] is event1
        assert events[1] is event2

    def test_iteration_preserves_order(self) -> None:
        batch = EventBatch(since=100, until=300, limit=10)

        events = []
        for ts in [200, 150, 250, 100]:
            evt = _make_mock_event(ts)
            batch.append(evt)
            events.append(evt)

        collected = list(batch)
        assert len(collected) == 4
        for i, evt in enumerate(collected):
            assert evt is events[i]

    def test_zero_limit(self) -> None:
        batch = EventBatch(since=100, until=200, limit=0)

        assert batch.is_full() is True
        assert batch.is_empty() is True

        event = _make_mock_event(150)

        with pytest.raises(OverflowError):
            batch.append(event)


class TestCreateFilter:
    def test_default_config(self) -> None:
        config = FilterConfig()
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_kinds(self) -> None:
        config = FilterConfig(kinds=[1, 3, 30023])
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_authors(self) -> None:
        valid_author = "a" * 64
        config = FilterConfig(authors=[valid_author])

        mock_filter = MagicMock()
        mock_filter.since.return_value = mock_filter
        mock_filter.until.return_value = mock_filter
        mock_filter.limit.return_value = mock_filter
        mock_filter.authors.return_value = mock_filter

        with patch("bigbrotr.services.synchronizer.utils.Filter", return_value=mock_filter):
            f = create_filter(since=1000, until=2000, config=config)

        mock_filter.authors.assert_called_once_with([valid_author])
        assert f is not None

    def test_with_ids(self) -> None:
        valid_id = "b" * 64
        config = FilterConfig(ids=[valid_id])

        mock_filter = MagicMock()
        mock_filter.since.return_value = mock_filter
        mock_filter.until.return_value = mock_filter
        mock_filter.limit.return_value = mock_filter
        mock_filter.ids.return_value = mock_filter

        with patch("bigbrotr.services.synchronizer.utils.Filter", return_value=mock_filter):
            f = create_filter(since=1000, until=2000, config=config)

        mock_filter.ids.assert_called_once_with([valid_id])
        assert f is not None

    def test_with_tag_filters(self) -> None:
        config = FilterConfig(tags={"e": ["event_id_1"], "t": ["hashtag"]})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_empty_tag_values(self) -> None:
        config = FilterConfig(tags={"e": []})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_invalid_tag_letter(self) -> None:
        config = FilterConfig(tags={"1": ["value"]})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_multi_letter_tag_key(self) -> None:
        config = FilterConfig(tags={"ee": ["value"]})
        f = create_filter(since=0, until=100, config=config)
        assert f is not None

    def test_with_all_options(self) -> None:
        config = FilterConfig(
            ids=["a" * 64],
            kinds=[1, 4],
            authors=["b" * 64],
            tags={"e": ["c" * 64], "p": ["d" * 64]},
            limit=1000,
        )

        mock_filter = MagicMock()
        mock_filter.since.return_value = mock_filter
        mock_filter.until.return_value = mock_filter
        mock_filter.limit.return_value = mock_filter
        mock_filter.kinds.return_value = mock_filter
        mock_filter.authors.return_value = mock_filter
        mock_filter.ids.return_value = mock_filter
        mock_filter.custom_tag.return_value = mock_filter

        with patch("bigbrotr.services.synchronizer.utils.Filter", return_value=mock_filter):
            f = create_filter(since=500, until=9999, config=config)

        mock_filter.kinds.assert_called_once()
        mock_filter.authors.assert_called_once()
        mock_filter.ids.assert_called_once()
        # Two tag letters with one value each = 2 custom_tag calls
        assert mock_filter.custom_tag.call_count == 2
        assert f is not None

    def test_with_custom_limit(self) -> None:
        config = FilterConfig(limit=42)
        f = create_filter(since=0, until=100, config=config)
        assert f is not None


class TestInsertBatch:
    async def test_empty_batch_noop(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0
        mock_synchronizer_brotr.insert_event_relay.assert_not_called()

    async def test_batch_with_valid_events(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr.insert_event_relay = AsyncMock(return_value=3)

        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        for ts in [120, 150, 180]:
            evt = _make_mock_event(ts)
            batch.append(evt)

        with patch("bigbrotr.services.synchronizer.utils.Event") as MockEvent:
            mock_event_instance = MagicMock()
            MockEvent.return_value = mock_event_instance

            with patch("bigbrotr.services.synchronizer.utils.EventRelay") as MockEventRelay:
                mock_er = MagicMock()
                MockEventRelay.return_value = mock_er

                inserted, invalid = await insert_batch(
                    batch, relay, mock_synchronizer_brotr, since=100, until=200
                )

        assert inserted == 3
        assert invalid == 0
        mock_synchronizer_brotr.insert_event_relay.assert_called_once()

    async def test_batch_with_invalid_signature(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        evt = _make_mock_event(150)
        evt.verify.return_value = False
        batch.append(evt)

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 1

    async def test_batch_with_out_of_range_timestamp(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        # Event at timestamp 150 is in batch range [100, 200]
        evt = _make_mock_event(150)
        batch.append(evt)

        # But insert_batch checks against a tighter window
        _inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=160, until=200
        )

        assert invalid == 1

    async def test_batch_with_event_parse_error(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        evt = _make_mock_event(150)
        evt.verify.side_effect = ValueError("parse failed")
        batch.append(evt)

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        # Parse errors are silently logged, not counted as invalid
        assert inserted == 0
        assert invalid == 0

    async def test_batch_with_type_error(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        evt = _make_mock_event(150)
        evt.verify.side_effect = TypeError("type error")
        batch.append(evt)

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0

    async def test_batch_with_overflow_error(self, mock_synchronizer_brotr: Brotr) -> None:
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        evt = _make_mock_event(150)
        evt.verify.side_effect = OverflowError("overflow")
        batch.append(evt)

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0

    async def test_batch_chunking(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr.config.batch.max_size = 2
        mock_synchronizer_brotr.insert_event_relay = AsyncMock(return_value=2)

        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        for ts in [120, 130, 140]:
            evt = _make_mock_event(ts)
            batch.append(evt)

        with patch("bigbrotr.services.synchronizer.utils.Event") as MockEvent:
            MockEvent.return_value = MagicMock()
            with patch("bigbrotr.services.synchronizer.utils.EventRelay") as MockEventRelay:
                MockEventRelay.return_value = MagicMock()

                inserted, _invalid = await insert_batch(
                    batch, relay, mock_synchronizer_brotr, since=100, until=200
                )

        # Should be called twice: chunk of 2 + chunk of 1
        assert mock_synchronizer_brotr.insert_event_relay.call_count == 2
        assert inserted == 4  # 2 + 2 from mock return_value

    async def test_batch_mixed_valid_and_invalid(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr.insert_event_relay = AsyncMock(return_value=1)

        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        good_evt = _make_mock_event(150)
        good_evt.verify.return_value = True
        batch.append(good_evt)

        bad_evt = _make_mock_event(160)
        bad_evt.verify.return_value = False
        batch.append(bad_evt)

        with patch("bigbrotr.services.synchronizer.utils.Event") as MockEvent:
            MockEvent.return_value = MagicMock()
            with patch("bigbrotr.services.synchronizer.utils.EventRelay") as MockEventRelay:
                MockEventRelay.return_value = MagicMock()

                inserted, invalid = await insert_batch(
                    batch, relay, mock_synchronizer_brotr, since=100, until=200
                )

        assert inserted == 1
        assert invalid == 1


class TestIterRelayEvents:
    @staticmethod
    def _make_fetch_result(events: list[MagicMock]) -> MagicMock:
        result = MagicMock()
        result.to_vec.return_value = events
        return result

    async def test_empty_relay_yields_nothing(self) -> None:
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=self._make_fetch_result([]))
        config = FilterConfig(limit=500)

        batches = [b async for b in iter_relay_events(client, 100, 1000, config, 10.0)]

        assert batches == []

    async def test_single_batch_under_limit(self) -> None:
        events = [_make_mock_event(200), _make_mock_event(300), _make_mock_event(400)]
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=self._make_fetch_result(events))
        config = FilterConfig(limit=500)

        batches = [b async for b in iter_relay_events(client, 100, 1000, config, 10.0)]

        assert len(batches) == 1
        assert batches[0].since == 100
        assert batches[0].until == 1000
        assert len(batches[0]) == 3

    async def test_full_batch_triggers_split(self) -> None:
        config = FilterConfig(limit=3)

        # Call 1: window [100, 200], 3 events → full → split, mid=150
        call1 = self._make_fetch_result(
            [
                _make_mock_event(120),
                _make_mock_event(160),
                _make_mock_event(180),
            ]
        )
        # Call 2: window [100, 150], 2 events → under limit → yield
        call2 = self._make_fetch_result(
            [
                _make_mock_event(120),
                _make_mock_event(140),
            ]
        )
        # Call 3: window [151, 200], 2 events → under limit → yield
        call3 = self._make_fetch_result(
            [
                _make_mock_event(160),
                _make_mock_event(180),
            ]
        )

        client = AsyncMock()
        client.fetch_events = AsyncMock(side_effect=[call1, call2, call3])

        batches = [b async for b in iter_relay_events(client, 100, 200, config, 10.0)]

        assert len(batches) == 2
        # First batch covers left half
        assert batches[0].since == 100
        assert batches[0].until == 150
        assert len(batches[0]) == 2
        # Second batch covers right half
        assert batches[1].since == 151
        assert batches[1].until == 200
        assert len(batches[1]) == 2

    async def test_single_second_window_yields_despite_full_batch(self) -> None:
        events = [_make_mock_event(500), _make_mock_event(500), _make_mock_event(500)]
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=self._make_fetch_result(events))
        config = FilterConfig(limit=3)

        batches = [b async for b in iter_relay_events(client, 500, 500, config, 10.0)]

        assert len(batches) == 1
        assert batches[0].since == 500
        assert batches[0].until == 500
        assert len(batches[0]) == 3

    async def test_exception_propagates(self) -> None:
        client = AsyncMock()
        client.fetch_events = AsyncMock(side_effect=TimeoutError("fetch timeout"))
        config = FilterConfig(limit=500)

        with pytest.raises(TimeoutError, match="fetch timeout"):
            async for _ in iter_relay_events(client, 100, 1000, config, 10.0):
                pass

    async def test_events_out_of_range_filtered(self) -> None:
        # Events outside [100, 200] are silently dropped by EventBatch
        events = [_make_mock_event(50), _make_mock_event(300)]
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=self._make_fetch_result(events))
        config = FilterConfig(limit=500)

        batches = [b async for b in iter_relay_events(client, 100, 200, config, 10.0)]

        # Batch is empty after filtering → treated as empty window
        assert batches == []

    async def test_nested_splits(self) -> None:
        config = FilterConfig(limit=2)

        # Window [0, 100]: 2 events → full → split, mid=50
        call1 = self._make_fetch_result([_make_mock_event(30), _make_mock_event(80)])
        # Window [0, 50]: 2 events → full → split, mid=25
        call2 = self._make_fetch_result([_make_mock_event(10), _make_mock_event(40)])
        # Window [0, 25]: 1 event → yield
        call3 = self._make_fetch_result([_make_mock_event(10)])
        # Window [26, 50]: 1 event → yield
        call4 = self._make_fetch_result([_make_mock_event(40)])
        # Window [51, 100]: 1 event → yield
        call5 = self._make_fetch_result([_make_mock_event(80)])

        client = AsyncMock()
        client.fetch_events = AsyncMock(side_effect=[call1, call2, call3, call4, call5])

        batches = [b async for b in iter_relay_events(client, 0, 100, config, 10.0)]

        assert len(batches) == 3
        # Ascending time order
        assert batches[0].until < batches[1].until < batches[2].until

    async def test_empty_window_between_batches(self) -> None:
        # Split that leads to an empty left half
        config_split = FilterConfig(limit=2)
        # Window [100, 200]: 2 events → full → split, mid=150
        call1 = self._make_fetch_result([_make_mock_event(160), _make_mock_event(180)])
        # Window [100, 150]: 0 events → empty → advance to 151
        call2 = self._make_fetch_result([])
        # Window [151, 200]: 2 events → full → since==until? No. split, mid=175
        call3 = self._make_fetch_result([_make_mock_event(160), _make_mock_event(180)])
        # Window [151, 175]: 1 event → yield
        call4 = self._make_fetch_result([_make_mock_event(160)])
        # Window [176, 200]: 1 event → yield
        call5 = self._make_fetch_result([_make_mock_event(180)])

        client = AsyncMock()
        client.fetch_events = AsyncMock(side_effect=[call1, call2, call3, call4, call5])

        batches = [b async for b in iter_relay_events(client, 100, 200, config_split, 10.0)]

        assert len(batches) == 2
        # Left half was empty, so batches start from the right
        assert batches[0].since == 151

    async def test_partial_completion_on_exception(self) -> None:
        config = FilterConfig(limit=2)

        # Window [100, 300]: 2 events (== limit) → split, mid=200
        call1 = self._make_fetch_result([_make_mock_event(150), _make_mock_event(250)])
        # Window [100, 200]: 1 event (< limit) → yield
        call2 = self._make_fetch_result([_make_mock_event(150)])
        # Third fetch (right half [201, 300]) raises
        client = AsyncMock()
        client.fetch_events = AsyncMock(side_effect=[call1, call2, OSError("connection lost")])

        batches: list[EventBatch] = []
        with pytest.raises(OSError, match="connection lost"):
            async for b in iter_relay_events(client, 100, 300, config, 10.0):
                batches.append(b)

        # First batch was yielded before the error
        assert len(batches) == 1
        assert batches[0].until == 200


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

    async def test_returns_zero_on_none(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)

        result = await delete_stale_cursors(query_brotr)

        assert result == 0


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
            concurrency=ConcurrencyConfig(cursor_flush_interval=25),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        assert sync.config.networks.tor.enabled is True
        assert sync.config.concurrency.cursor_flush_interval == 25

    def test_from_dict(self, mock_synchronizer_brotr: Brotr) -> None:
        data = {
            "networks": {"tor": {"enabled": True}},
            "concurrency": {"cursor_flush_interval": 25},
        }
        sync = Synchronizer.from_dict(data, brotr=mock_synchronizer_brotr)

        assert sync.config.networks.tor.enabled is True
        assert sync.config.concurrency.cursor_flush_interval == 25


class TestSynchronizerFetchRelays:
    async def test_fetch_relays_empty(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        relays = await sync.fetch_relays()

        assert relays == []

    async def test_fetch_relays_with_results(self, mock_synchronizer_brotr: Brotr) -> None:
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


class TestSynchronizerFetchCursors:
    async def test_returns_empty_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        result = await sync.fetch_cursors()
        assert result == {}

    async def test_delegates_to_get_service_state(self, mock_synchronizer_brotr: Brotr) -> None:
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


class TestSynchronizerGetStartTime:
    def test_returns_default_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
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
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time(relay, {})
        assert result == 0


class TestSynchronizerRun:
    async def test_run_no_relays(self, mock_synchronizer_brotr: Brotr) -> None:
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        await sync.run()

    async def test_run_with_relays_calls_run_sync(self, mock_synchronizer_brotr: Brotr) -> None:
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


class TestSynchronizerRunSync:
    async def test_run_sync_empty_list(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        result = await sync._run_sync([], {})

        assert result == 0

    async def test_run_sync_success_aggregates_results(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://success.relay.com")
        sync._fetch_and_insert = AsyncMock(return_value=(10, 2, 1000))  # type: ignore[method-assign]
        result = await sync._run_sync([relay], {})

        assert result == 10
        sync.set_gauge.assert_any_call("events_synced", 10)
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_run_sync_handles_task_group_errors(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("unexpected")
        )
        result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_timeout_counts_as_failure(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://slow.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("overall timeout")
        )
        result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_postgres_error_counts_as_failure(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://db-error.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("db error")
        )
        result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_os_error_counts_as_failure(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://net-error.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=OSError("connection refused")
        )
        result = await sync._run_sync([relay], {})

        assert result == 0
        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_run_sync_cursor_update_flushed(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=50),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(1, 0, 1000))  # type: ignore[method-assign]
        await sync._run_sync([relay], {})

        mock_synchronizer_brotr.upsert_service_state.assert_called()

    async def test_run_sync_cursor_periodic_flush(self, mock_synchronizer_brotr: Brotr) -> None:
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

        sync._fetch_and_insert = AsyncMock(return_value=(1, 0, 1000))  # type: ignore[method-assign]
        await sync._run_sync(relays, {})

        # Multiple calls: periodic flushes + final flush
        assert mock_synchronizer_brotr.upsert_service_state.call_count >= 2

    async def test_run_sync_final_cursor_flush_error(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            concurrency=ConcurrencyConfig(cursor_flush_interval=999),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")

        mock_synchronizer_brotr.upsert_service_state = AsyncMock(
            side_effect=asyncpg.PostgresError("flush failed")
        )

        sync._fetch_and_insert = AsyncMock(return_value=(1, 0, 1000))  # type: ignore[method-assign]
        # Should not raise
        result = await sync._run_sync([relay], {})

        assert result == 1

    async def test_run_sync_skip_when_start_ge_end(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(
                default_start=999_999_999_999,  # Far future
                use_relay_state=False,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(5, 0, 1000))  # type: ignore[method-assign]
        await sync._run_sync([relay], {})

        sync._fetch_and_insert.assert_not_called()

    async def test_run_sync_with_cached_cursor(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
        cursors: dict[str, int] = {
            "wss://relay.example.com": 100,
        }

        sync._fetch_and_insert = AsyncMock(return_value=(1, 0, 1000))  # type: ignore[method-assign]
        result = await sync._run_sync([relay], cursors)

        assert result == 1

    async def test_run_sync_no_cursor_update_when_none(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        relay = Relay("wss://relay.example.com")
        # cursor_value is None → no cursor update
        sync._fetch_and_insert = AsyncMock(return_value=(0, 0, None))  # type: ignore[method-assign]
        await sync._run_sync([relay], {})

        mock_synchronizer_brotr.upsert_service_state.assert_not_called()


class TestSynchronizerPhaseTimeout:
    async def test_max_duration_skips_relay(self, mock_synchronizer_brotr: Brotr) -> None:
        import asyncio
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(
                relay_clearnet=60.0,
                relay_tor=60.0,
                relay_i2p=60.0,
                relay_loki=60.0,
                max_duration=60.0,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        phase_start = time_mod.monotonic() - 61.0  # 61s ago -> exceeds 60s limit
        batch = SyncBatchState(
            cursor_updates=[], cursor_lock=asyncio.Lock(), cursor_flush_interval=50
        )

        sync._fetch_and_insert = AsyncMock(return_value=(5, 0, 1000))  # type: ignore[method-assign]
        result = await sync._sync_single_relay(relay, {}, batch, phase_start)

        assert result is None
        sync._fetch_and_insert.assert_not_called()

    async def test_max_duration_within_limit_proceeds(self, mock_synchronizer_brotr: Brotr) -> None:
        import asyncio
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=3600.0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        relay = Relay("wss://relay.example.com")
        phase_start = time_mod.monotonic()  # Just started -> within limit
        batch = SyncBatchState(
            cursor_updates=[], cursor_lock=asyncio.Lock(), cursor_flush_interval=50
        )

        sync._fetch_and_insert = AsyncMock(return_value=(10, 0, 1000))  # type: ignore[method-assign]
        result = await sync._sync_single_relay(relay, {}, batch, phase_start)

        assert result == (10, 0)

    async def test_max_duration_none_allows_unlimited(self, mock_synchronizer_brotr: Brotr) -> None:
        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(max_duration=None),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(10, 0, 1000))  # type: ignore[method-assign]
        result = await sync._run_sync([relay], {})

        assert result == 10
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_max_duration_run_sync_integration(self, mock_synchronizer_brotr: Brotr) -> None:
        import time as time_mod

        config = SynchronizerConfig(
            timeouts=TimeoutsConfig(
                relay_clearnet=60.0,
                relay_tor=60.0,
                relay_i2p=60.0,
                relay_loki=60.0,
                max_duration=60.0,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        original_monotonic = time_mod.monotonic

        call_count = 0

        def fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return original_monotonic()
            return original_monotonic() + 61.0

        sync._fetch_and_insert = AsyncMock(return_value=(5, 0, 1000))  # type: ignore[method-assign]
        with patch(
            "bigbrotr.services.synchronizer.service.time.monotonic", side_effect=fake_monotonic
        ):
            result = await sync._run_sync([relay], {})

        assert result == 0
        sync._fetch_and_insert.assert_not_called()
        sync.set_gauge.assert_any_call("relays_scanned", 0)

    async def test_shutdown_skips_relay(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]
        sync.request_shutdown()

        relay = Relay("wss://relay.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(5, 0, 1000))  # type: ignore[method-assign]
        result = await sync._run_sync([relay], {})

        assert result == 0
        sync._fetch_and_insert.assert_not_called()
        sync.set_gauge.assert_any_call("relays_scanned", 0)


# ============================================================================
# Metrics
# ============================================================================


class TestSynchronizerMetrics:
    async def test_run_sync_emits_gauges(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.set_gauge = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay1.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(5, 1, 1000))  # type: ignore[method-assign]
        await sync._run_sync([relay], {})

        sync.set_gauge.assert_any_call("events_synced", 5)
        sync.set_gauge.assert_any_call("relays_scanned", 1)

    async def test_run_sync_emits_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")
        sync._fetch_and_insert = AsyncMock(return_value=(10, 2, 1000))  # type: ignore[method-assign]
        await sync._run_sync([relay], {})

        sync.inc_counter.assert_any_call("total_events_synced", 10)
        sync.inc_counter.assert_any_call("total_events_invalid", 2)

    async def test_failed_relay_emits_sync_failures(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("timeout")
        )
        await sync._run_sync([relay], {})

        sync.inc_counter.assert_any_call("total_sync_failures", 1)

    async def test_failed_relay_no_event_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync.inc_counter = MagicMock()  # type: ignore[method-assign]

        relay = Relay("wss://failing.relay.com")
        sync._fetch_and_insert = AsyncMock(  # type: ignore[method-assign]
            side_effect=TimeoutError("timeout")
        )
        await sync._run_sync([relay], {})

        # Event counters should be called with 0 (no successful events)
        sync.inc_counter.assert_any_call("total_events_synced", 0)
        sync.inc_counter.assert_any_call("total_events_invalid", 0)

    async def test_synchronize_returns_events_synced(self, mock_synchronizer_brotr: Brotr) -> None:
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
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)

        result = await sync.synchronize()

        assert result == 0


# ============================================================================
# Network Filter
# ============================================================================


class TestSynchronizerNetworkFilter:
    async def test_fetch_relays_filters_disabled_networks(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
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
