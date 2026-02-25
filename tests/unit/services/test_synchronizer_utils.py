"""
Unit tests for services.synchronizer.utils module.

Tests:
- _log structured logging utility
- EventBatch class (append, bounds, overflow, iteration, min/max tracking)
- create_filter: filter construction with kinds, authors, ids, tags
- insert_batch: batch insertion with valid, invalid, empty, chunked events
- sync_relay_events: per-relay sync logic (success, empty, timeout, OSError, proxy)
- TimeoutsConfig.get_relay_timeout additional coverage
- RelayOverride configuration model
- SyncContext frozen dataclass
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.core.brotr import TimeoutsConfig as BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import NetworksConfig, TorConfig
from bigbrotr.services.synchronizer import (
    EventBatch,
    FilterConfig,
    RelayOverride,
    RelayOverrideTimeouts,
    SyncContext,
    TimeoutsConfig,
)
from bigbrotr.services.synchronizer.utils import (
    _log,
    create_filter,
    insert_batch,
    sync_relay_events,
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
    """Set PRIVATE_KEY environment variable for all synchronizer utils tests."""
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
# Helpers
# ============================================================================


def _make_mock_event(created_at_secs: int) -> MagicMock:
    """Create a mock nostr-sdk event with all fields needed by insert_batch."""
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
# _log Utility Tests
# ============================================================================


class TestLogUtility:
    """Tests for the _log structured logging utility."""

    def test_log_info_level(self) -> None:
        """Test _log at INFO level with kwargs."""
        with patch("bigbrotr.services.synchronizer.utils._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            _log("INFO", "test_message", relay="wss://test.com", count=5)
            mock_logger.log.assert_called_once()
            args = mock_logger.log.call_args
            assert args[0][0] == 20  # logging.INFO
            assert "test_message" in args[0][1]

    def test_log_when_disabled(self) -> None:
        """Test _log is a no-op when level is disabled."""
        with patch("bigbrotr.services.synchronizer.utils._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = False
            _log("DEBUG", "should_not_log")
            mock_logger.log.assert_not_called()


# ============================================================================
# EventBatch Tests
# ============================================================================


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

        event1 = _make_mock_event(100)
        batch.append(event1)

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

    def test_append_only_updates_min_when_smaller(self) -> None:
        """Test min_created_at only updates when a smaller timestamp arrives."""
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
        """Test batch with since == until accepts exactly that timestamp."""
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
        """Test is_full method."""
        batch = EventBatch(since=100, until=200, limit=2)

        assert batch.is_full() is False

        event1 = _make_mock_event(150)
        batch.append(event1)
        assert batch.is_full() is False

        event2 = _make_mock_event(160)
        batch.append(event2)
        assert batch.is_full() is True

    def test_is_full_at_limit_one(self) -> None:
        """Test is_full with limit=1."""
        batch = EventBatch(since=100, until=200, limit=1)
        assert batch.is_full() is False

        batch.append(_make_mock_event(150))
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

    def test_len_matches_size(self) -> None:
        """Test __len__ always equals .size attribute."""
        batch = EventBatch(since=100, until=200, limit=10)

        assert len(batch) == batch.size == 0

        batch.append(_make_mock_event(150))
        assert len(batch) == batch.size == 1

        batch.append(_make_mock_event(160))
        assert len(batch) == batch.size == 2

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

    def test_iteration_preserves_order(self) -> None:
        """Test iteration returns events in insertion order."""
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
        """Test batch with zero limit."""
        batch = EventBatch(since=100, until=200, limit=0)

        assert batch.is_full() is True
        assert batch.is_empty() is True

        event = _make_mock_event(150)

        with pytest.raises(OverflowError):
            batch.append(event)


# ============================================================================
# create_filter Tests
# ============================================================================


class TestCreateFilter:
    """Tests for create_filter function."""

    def test_default_config(self) -> None:
        """Test filter creation with default FilterConfig."""
        config = FilterConfig()
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_kinds(self) -> None:
        """Test filter creation with specific event kinds."""
        config = FilterConfig(kinds=[1, 3, 30023])
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_authors(self) -> None:
        """Test filter creation with author pubkeys calls Filter.authors()."""
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
        """Test filter creation with event IDs calls Filter.ids()."""
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
        """Test filter creation with tag filters."""
        config = FilterConfig(tags={"e": ["event_id_1"], "t": ["hashtag"]})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_empty_tag_values(self) -> None:
        """Test filter creation with empty tag value list (skipped)."""
        config = FilterConfig(tags={"e": []})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_invalid_tag_letter(self) -> None:
        """Test filter creation with non-alphabet tag key logs warning and skips."""
        config = FilterConfig(tags={"1": ["value"]})
        f = create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_multi_letter_tag_key(self) -> None:
        """Test filter creation with multi-character tag key (ignored)."""
        config = FilterConfig(tags={"ee": ["value"]})
        f = create_filter(since=0, until=100, config=config)
        assert f is not None

    def test_with_all_options(self) -> None:
        """Test filter creation with all options set calls all Filter methods."""
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
        """Test filter creation respects the configured limit."""
        config = FilterConfig(limit=42)
        f = create_filter(since=0, until=100, config=config)
        assert f is not None


# ============================================================================
# insert_batch Tests
# ============================================================================


class TestInsertBatch:
    """Tests for insert_batch function."""

    async def test_empty_batch_noop(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test empty batch returns zeros without calling DB."""
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        inserted, invalid = await insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0
        mock_synchronizer_brotr.insert_event_relay.assert_not_called()

    async def test_batch_with_valid_events(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test batch insertion with valid events calls insert_event_relay."""
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
        """Test that events with invalid signatures are counted as invalid."""
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
        """Test that events with timestamps outside since/until are invalid."""
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
        """Test that event parse errors are handled gracefully."""
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
        """Test that TypeError during event processing is caught."""
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
        """Test that OverflowError during event processing is caught."""
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
        """Test batch is chunked by brotr.config.batch.max_size."""
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
        """Test batch with a mix of valid and invalid-signature events."""
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


# ============================================================================
# sync_relay_events Tests
# ============================================================================


class TestSyncRelayEvents:
    """Tests for sync_relay_events function."""

    def _make_sync_context(self, brotr: Brotr) -> SyncContext:
        """Build a SyncContext for testing."""
        from nostr_sdk import Keys

        keys = Keys.parse(VALID_HEX_KEY)
        return SyncContext(
            filter_config=FilterConfig(),
            network_config=NetworksConfig(),
            request_timeout=10.0,
            brotr=brotr,
            keys=keys,
        )

    async def test_sync_with_events(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync returns events when relay responds with events."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        mock_event = _make_mock_event(500)
        mock_events_result.to_vec.return_value = [mock_event]
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with (
            patch(
                "bigbrotr.services.synchronizer.utils.create_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch(
                "bigbrotr.services.synchronizer.utils.insert_batch",
                new_callable=AsyncMock,
                return_value=(5, 1),
            ) as mock_insert,
        ):
            synced, invalid = await sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 5
        assert invalid == 1
        mock_insert.assert_called_once()

    async def test_sync_with_no_events(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync with empty event list from relay."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        mock_events_result.to_vec.return_value = []
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            synced, invalid = await sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0

    async def test_sync_timeout_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync handles TimeoutError gracefully."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=TimeoutError("connect timeout"))
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            synced, invalid = await sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0

    async def test_sync_os_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync handles OSError gracefully."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=OSError("network error"))
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            synced, invalid = await sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0

    async def test_sync_disconnect_called(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that client disconnect and shutdown are called after sync."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        mock_events_result.to_vec.return_value = []
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

        mock_client.disconnect.assert_called_once()
        mock_client.shutdown.assert_called_once()

    async def test_sync_shutdown_called_even_on_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that shutdown is always called (finally block) even on error."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=TimeoutError("boom"))
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

        mock_client.shutdown.assert_called_once()

    async def test_sync_with_proxy_for_tor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync with a Tor relay uses correct proxy URL."""
        from nostr_sdk import Keys

        relay = Relay("wss://example.onion")
        keys = Keys.parse(VALID_HEX_KEY)
        ctx = SyncContext(
            filter_config=FilterConfig(),
            network_config=NetworksConfig(tor=TorConfig(enabled=True)),
            request_timeout=10.0,
            brotr=mock_synchronizer_brotr,
            keys=keys,
        )

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        mock_events_result.to_vec.return_value = []
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch(
            "bigbrotr.services.synchronizer.utils.create_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_create:
            await sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

        mock_create.assert_called_once()

    async def test_sync_overflow_in_batch_append(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that OverflowError during batch.append breaks the loop."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        events = [_make_mock_event(500), _make_mock_event(600)]
        mock_events_result.to_vec.return_value = events
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        original_event_batch = EventBatch

        class LimitedBatch(original_event_batch):  # type: ignore[misc]
            """Batch that overflows after 1 event."""

            def __init__(self, since: int, until: int, limit: int) -> None:
                super().__init__(since, until, limit=1)

        with (
            patch(
                "bigbrotr.services.synchronizer.utils.create_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch("bigbrotr.services.synchronizer.utils.EventBatch", LimitedBatch),
            patch(
                "bigbrotr.services.synchronizer.utils.insert_batch",
                new_callable=AsyncMock,
                return_value=(1, 0),
            ),
        ):
            synced, _invalid = await sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 1


# ============================================================================
# TimeoutsConfig Additional Tests
# ============================================================================


class TestTimeoutsConfigGetRelayTimeout:
    """Additional coverage for TimeoutsConfig.get_relay_timeout."""

    def test_get_relay_timeout_clearnet_explicit(self) -> None:
        """Test CLEARNET returns relay_clearnet."""
        config = TimeoutsConfig(relay_clearnet=500.0)
        assert config.get_relay_timeout(NetworkType.CLEARNET) == 500.0

    def test_get_relay_timeout_i2p(self) -> None:
        """Test I2P returns relay_i2p."""
        config = TimeoutsConfig(relay_i2p=2000.0)
        assert config.get_relay_timeout(NetworkType.I2P) == 2000.0

    def test_get_relay_timeout_loki(self) -> None:
        """Test LOKI returns relay_loki."""
        config = TimeoutsConfig(relay_loki=2500.0)
        assert config.get_relay_timeout(NetworkType.LOKI) == 2500.0


# ============================================================================
# RelayOverride Tests
# ============================================================================


class TestRelayOverride:
    """Tests for RelayOverride configuration model."""

    def test_default_timeouts(self) -> None:
        """Test override with default (None) timeouts."""
        override = RelayOverride(url="wss://relay.example.com")
        assert override.timeouts.request is None
        assert override.timeouts.relay is None

    def test_custom_timeouts(self) -> None:
        """Test override with custom timeouts."""
        override = RelayOverride(
            url="wss://relay.example.com",
            timeouts=RelayOverrideTimeouts(request=30.0, relay=600.0),
        )
        assert override.timeouts.request == 30.0
        assert override.timeouts.relay == 600.0


# ============================================================================
# SyncContext Tests
# ============================================================================


class TestSyncContext:
    """Tests for the SyncContext frozen dataclass."""

    def test_sync_context_immutable(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test SyncContext is frozen (immutable)."""
        from nostr_sdk import Keys

        keys = Keys.parse(VALID_HEX_KEY)
        ctx = SyncContext(
            filter_config=FilterConfig(),
            network_config=NetworksConfig(),
            request_timeout=10.0,
            brotr=mock_synchronizer_brotr,
            keys=keys,
        )
        assert ctx.request_timeout == 10.0
        assert ctx.filter_config.limit == 500

        with pytest.raises(AttributeError):
            ctx.request_timeout = 20.0  # type: ignore[misc]
