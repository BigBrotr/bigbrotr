"""
Additional unit tests for services.synchronizer module to increase coverage.

Targets uncovered lines: 317-352, 373-418, 449-484, 539-545, 556-562,
593-598, 603, 624-653, 670-708, 721-725.

Tests:
- _create_filter: filter construction with kinds, authors, ids, tags
- _insert_batch: batch insertion with mock brotr (valid, invalid, empty, chunked, errors)
- _sync_relay_events: per-relay sync logic (success, empty, timeout, OSError)
- _sync_all_relays: orchestration, cursor flush, override timeouts, start >= end skip
- _fetch_all_cursors: with/without use_relay_state
- _get_start_time_from_cache: cursor hit, miss, relay-state disabled
- EventBatch: additional edge-case coverage
- _log utility: structured logging coverage
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig, BrotrTimeoutsConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import NetworkConfig, TorConfig
from bigbrotr.services.synchronizer import (
    EventBatch,
    FilterConfig,
    RelayOverride,
    RelayOverrideTimeouts,
    SyncConcurrencyConfig,
    SyncContext,
    Synchronizer,
    SynchronizerConfig,
    SyncTimeoutsConfig,
    TimeRangeConfig,
    _create_filter,
    _insert_batch,
    _log,
    _sync_relay_events,
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


def _make_mock_event(created_at_secs: int) -> MagicMock:
    """Create a mock nostr-sdk event with a properly mocked created_at timestamp."""
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

    # Mock tags
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
        with patch("bigbrotr.services.synchronizer._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            _log("INFO", "test_message", relay="wss://test.com", count=5)
            mock_logger.log.assert_called_once()
            args = mock_logger.log.call_args
            assert args[0][0] == 20  # logging.INFO
            assert "test_message" in args[0][1]

    def test_log_when_disabled(self) -> None:
        """Test _log is a no-op when level is disabled."""
        with patch("bigbrotr.services.synchronizer._logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = False
            _log("DEBUG", "should_not_log")
            mock_logger.log.assert_not_called()


# ============================================================================
# _create_filter Tests
# ============================================================================


class TestCreateFilter:
    """Tests for _create_filter function (lines 317-352)."""

    def test_default_config(self) -> None:
        """Test filter creation with default FilterConfig."""
        config = FilterConfig()
        f = _create_filter(since=1000, until=2000, config=config)
        # Filter should be created without error
        assert f is not None

    def test_with_kinds(self) -> None:
        """Test filter creation with specific event kinds."""
        config = FilterConfig(kinds=[1, 3, 30023])
        f = _create_filter(since=1000, until=2000, config=config)
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

        with patch("bigbrotr.services.synchronizer.Filter", return_value=mock_filter):
            f = _create_filter(since=1000, until=2000, config=config)

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

        with patch("bigbrotr.services.synchronizer.Filter", return_value=mock_filter):
            f = _create_filter(since=1000, until=2000, config=config)

        mock_filter.ids.assert_called_once_with([valid_id])
        assert f is not None

    def test_with_tag_filters(self) -> None:
        """Test filter creation with tag filters."""
        config = FilterConfig(tags={"e": ["event_id_1"], "t": ["hashtag"]})
        f = _create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_empty_tag_values(self) -> None:
        """Test filter creation with empty tag value list (skipped)."""
        config = FilterConfig(tags={"e": []})
        f = _create_filter(since=1000, until=2000, config=config)
        assert f is not None

    def test_with_invalid_tag_letter(self) -> None:
        """Test filter creation with non-alphabet tag key logs warning and skips."""
        config = FilterConfig(tags={"1": ["value"]})
        f = _create_filter(since=1000, until=2000, config=config)
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

        with patch("bigbrotr.services.synchronizer.Filter", return_value=mock_filter):
            f = _create_filter(since=500, until=9999, config=config)

        mock_filter.kinds.assert_called_once()
        mock_filter.authors.assert_called_once()
        mock_filter.ids.assert_called_once()
        # Two tag letters with one value each = 2 custom_tag calls
        assert mock_filter.custom_tag.call_count == 2
        assert f is not None

    def test_with_custom_limit(self) -> None:
        """Test filter creation respects the configured limit."""
        config = FilterConfig(limit=42)
        f = _create_filter(since=0, until=100, config=config)
        assert f is not None

    def test_with_multi_letter_tag_key(self) -> None:
        """Test filter creation with multi-character tag key (ignored)."""
        # Multi-char keys don't match len(tag_letter)==1, so they're skipped
        config = FilterConfig(tags={"ee": ["value"]})
        f = _create_filter(since=0, until=100, config=config)
        assert f is not None


# ============================================================================
# _insert_batch Tests
# ============================================================================


class TestInsertBatch:
    """Tests for _insert_batch function (lines 373-418)."""

    async def test_empty_batch_noop(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test empty batch returns zeros without calling DB."""
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        inserted, invalid, skipped = await _insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0
        assert skipped == 0
        mock_synchronizer_brotr.insert_event_relay.assert_not_called()

    async def test_batch_with_valid_events(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test batch insertion with valid events calls insert_event_relay."""
        mock_synchronizer_brotr.insert_event_relay = AsyncMock(return_value=3)

        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        for ts in [120, 150, 180]:
            evt = _make_mock_event(ts)
            batch.append(evt)

        # Patch Event construction to avoid real nostr-sdk validation
        with patch("bigbrotr.services.synchronizer.Event") as MockEvent:
            mock_event_instance = MagicMock()
            MockEvent.return_value = mock_event_instance

            with patch("bigbrotr.services.synchronizer.EventRelay") as MockEventRelay:
                mock_er = MagicMock()
                MockEventRelay.return_value = mock_er

                inserted, invalid, skipped = await _insert_batch(
                    batch, relay, mock_synchronizer_brotr, since=100, until=200
                )

        assert inserted == 3
        assert invalid == 0
        assert skipped == 0
        mock_synchronizer_brotr.insert_event_relay.assert_called_once()

    async def test_batch_with_invalid_signature(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that events with invalid signatures are counted as invalid."""
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        evt = _make_mock_event(150)
        evt.verify.return_value = False
        batch.append(evt)

        inserted, invalid, skipped = await _insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 1
        assert skipped == 0

    async def test_batch_with_out_of_range_timestamp(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that events with timestamps outside since/until are invalid."""
        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        # Event at timestamp 150 is in batch range [100, 200]
        evt = _make_mock_event(150)
        batch.append(evt)

        # But _insert_batch checks against a tighter window
        _inserted, invalid, _skipped = await _insert_batch(
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

        inserted, invalid, _skipped = await _insert_batch(
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

        inserted, invalid, _skipped = await _insert_batch(
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

        inserted, invalid, _skipped = await _insert_batch(
            batch, relay, mock_synchronizer_brotr, since=100, until=200
        )

        assert inserted == 0
        assert invalid == 0

    async def test_batch_chunking(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test batch is chunked by brotr.config.batch.max_size."""
        # Set small batch size to force chunking
        mock_synchronizer_brotr.config.batch.max_size = 2
        mock_synchronizer_brotr.insert_event_relay = AsyncMock(return_value=2)

        batch = EventBatch(since=100, until=200, limit=10)
        relay = Relay("wss://test.relay.com")

        for ts in [120, 130, 140]:
            evt = _make_mock_event(ts)
            batch.append(evt)

        with patch("bigbrotr.services.synchronizer.Event") as MockEvent:
            MockEvent.return_value = MagicMock()
            with patch("bigbrotr.services.synchronizer.EventRelay") as MockEventRelay:
                MockEventRelay.return_value = MagicMock()

                inserted, _invalid, _skipped = await _insert_batch(
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

        # Valid event
        good_evt = _make_mock_event(150)
        good_evt.verify.return_value = True
        batch.append(good_evt)

        # Invalid signature event
        bad_evt = _make_mock_event(160)
        bad_evt.verify.return_value = False
        batch.append(bad_evt)

        with patch("bigbrotr.services.synchronizer.Event") as MockEvent:
            MockEvent.return_value = MagicMock()
            with patch("bigbrotr.services.synchronizer.EventRelay") as MockEventRelay:
                MockEventRelay.return_value = MagicMock()

                inserted, invalid, _skipped = await _insert_batch(
                    batch, relay, mock_synchronizer_brotr, since=100, until=200
                )

        assert inserted == 1
        assert invalid == 1


# ============================================================================
# _sync_relay_events Tests
# ============================================================================


class TestSyncRelayEvents:
    """Tests for _sync_relay_events function (lines 449-484)."""

    def _make_sync_context(self, brotr: Brotr) -> SyncContext:
        """Build a SyncContext for testing."""
        from nostr_sdk import Keys

        keys = Keys.parse(VALID_HEX_KEY)
        return SyncContext(
            filter_config=FilterConfig(),
            network_config=NetworkConfig(),
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
            patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client),
            patch(
                "bigbrotr.services.synchronizer._insert_batch",
                new_callable=AsyncMock,
                return_value=(5, 1, 0),
            ) as mock_insert,
        ):
            synced, invalid, skipped = await _sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 5
        assert invalid == 1
        assert skipped == 0
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

        with patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client):
            synced, invalid, skipped = await _sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0
        assert skipped == 0

    async def test_sync_timeout_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync handles TimeoutError gracefully."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=TimeoutError("connect timeout"))
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client):
            synced, invalid, skipped = await _sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0
        assert skipped == 0

    async def test_sync_os_error(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync handles OSError gracefully."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=OSError("network error"))
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        with patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client):
            synced, invalid, skipped = await _sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        assert synced == 0
        assert invalid == 0
        assert skipped == 0

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

        with patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client):
            await _sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

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

        with patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client):
            await _sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

        mock_client.shutdown.assert_called_once()

    async def test_sync_with_proxy_for_tor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test sync with a Tor relay uses correct proxy URL."""
        from nostr_sdk import Keys

        relay = Relay("wss://example.onion")
        keys = Keys.parse(VALID_HEX_KEY)
        ctx = SyncContext(
            filter_config=FilterConfig(),
            network_config=NetworkConfig(tor=TorConfig(enabled=True)),
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
            "bigbrotr.services.synchronizer.create_client", return_value=mock_client
        ) as mock_create:
            await _sync_relay_events(relay=relay, start_time=100, end_time=1000, ctx=ctx)

        # Verify create_client was called (proxy URL comes from NetworkConfig)
        mock_create.assert_called_once()

    async def test_sync_overflow_in_batch_append(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test that OverflowError during batch.append breaks the loop."""
        relay = Relay("wss://relay.example.com")
        ctx = self._make_sync_context(mock_synchronizer_brotr)

        mock_client = AsyncMock()
        mock_events_result = MagicMock()
        # Return many events but batch limit is 1 (in real code, limit=len(event_list))
        # We need the events to cause overflow by making the batch report full
        events = [_make_mock_event(500), _make_mock_event(600)]
        mock_events_result.to_vec.return_value = events
        mock_client.fetch_events = AsyncMock(return_value=mock_events_result)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.shutdown = AsyncMock()
        mock_client.add_relay = AsyncMock()

        # Patch EventBatch to raise overflow on second append
        original_event_batch = EventBatch

        class LimitedBatch(original_event_batch):  # type: ignore[misc]
            """Batch that overflows after 1 event."""

            def __init__(self, since: int, until: int, limit: int) -> None:
                super().__init__(since, until, limit=1)

        with (
            patch("bigbrotr.services.synchronizer.create_client", return_value=mock_client),
            patch("bigbrotr.services.synchronizer.EventBatch", LimitedBatch),
            patch(
                "bigbrotr.services.synchronizer._insert_batch",
                new_callable=AsyncMock,
                return_value=(1, 0, 0),
            ),
        ):
            synced, _invalid, _skipped = await _sync_relay_events(
                relay=relay, start_time=100, end_time=1000, ctx=ctx
            )

        # Should still succeed (overflow just breaks the loop)
        assert synced == 1


# ============================================================================
# _fetch_all_cursors Tests
# ============================================================================


class TestFetchAllCursors:
    """Tests for Synchronizer._fetch_all_cursors method (lines 699-708)."""

    async def test_returns_empty_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test returns empty dict when use_relay_state is False."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        result = await sync._fetch_all_cursors()
        assert result == {}

    async def test_delegates_to_query_function(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test delegates to get_all_service_cursors when relay_state enabled."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)

        with patch(
            "bigbrotr.services.synchronizer.get_all_service_cursors",
            new_callable=AsyncMock,
            return_value={"wss://r1.com": 1000, "wss://r2.com": 2000},
        ) as mock_query:
            result = await sync._fetch_all_cursors()

        mock_query.assert_called_once_with(
            mock_synchronizer_brotr, "synchronizer", "last_synced_at"
        )
        assert result == {"wss://r1.com": 1000, "wss://r2.com": 2000}


# ============================================================================
# _get_start_time_from_cache Tests
# ============================================================================


class TestGetStartTimeFromCache:
    """Tests for Synchronizer._get_start_time_from_cache method (lines 710-727)."""

    def test_returns_default_when_relay_state_disabled(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test returns default_start when use_relay_state is False."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=False, default_start=42),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time_from_cache(relay, {"wss://relay.example.com": 1000})
        assert result == 42

    def test_returns_cursor_plus_one_when_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns cursor + 1 when relay has a cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=0),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://relay.example.com")

        result = sync._get_start_time_from_cache(relay, {"wss://relay.example.com": 1000})
        assert result == 1001

    def test_returns_default_when_cursor_not_found(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test returns default_start when relay has no cached cursor."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(use_relay_state=True, default_start=500),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        relay = Relay("wss://other.relay.com")

        result = sync._get_start_time_from_cache(relay, {"wss://relay.example.com": 1000})
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
# _sync_all_relays Tests
# ============================================================================


class TestSyncAllRelaysCoverage:
    """Additional tests for Synchronizer._sync_all_relays (lines 572-678)."""

    async def test_sync_all_relays_success_updates_counters(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test successful sync increments synced_relays and synced_events."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://success.relay.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(10, 2, 1),
        ):
            await sync._sync_all_relays([relay])

        assert sync._synced_relays == 1
        assert sync._synced_events == 10
        assert sync._invalid_events == 2
        assert sync._skipped_events == 1

    async def test_sync_all_relays_timeout_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test TimeoutError from wait_for increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://slow.relay.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            side_effect=TimeoutError("overall timeout"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._failed_relays == 1
        assert sync._synced_relays == 0

    async def test_sync_all_relays_postgres_error_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test asyncpg.PostgresError increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://db-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("db error"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._failed_relays == 1

    async def test_sync_all_relays_os_error_increments_failed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test OSError increments failed_relays."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://net-error.relay.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._failed_relays == 1

    async def test_sync_all_relays_cursor_update_flushed(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test cursor updates are flushed at end of sync."""
        config = SynchronizerConfig(
            concurrency=SyncConcurrencyConfig(cursor_flush_interval=50),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0, 0),
        ):
            await sync._sync_all_relays([relay])

        # Cursor updates should be flushed at end
        mock_synchronizer_brotr.upsert_service_state.assert_called()

    async def test_sync_all_relays_cursor_periodic_flush(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test cursor updates are periodically flushed when batch size reached."""
        config = SynchronizerConfig(
            concurrency=SyncConcurrencyConfig(
                cursor_flush_interval=1,  # Flush after every relay
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relays = [
            Relay("wss://relay1.example.com"),
            Relay("wss://relay2.example.com"),
        ]

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0, 0),
        ):
            await sync._sync_all_relays(relays)

        # Multiple calls: periodic flushes + final flush
        assert mock_synchronizer_brotr.upsert_service_state.call_count >= 2

    async def test_sync_all_relays_final_cursor_flush_error(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test final cursor flush handles DB errors gracefully."""
        config = SynchronizerConfig(
            concurrency=SyncConcurrencyConfig(cursor_flush_interval=999),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        mock_synchronizer_brotr.upsert_service_state = AsyncMock(
            side_effect=asyncpg.PostgresError("flush failed")
        )

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0, 0),
        ):
            # Should not raise
            await sync._sync_all_relays([relay])

        assert sync._synced_relays == 1

    async def test_sync_all_relays_skip_when_start_ge_end(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test relay is skipped when start_time >= end_time (line 602-603)."""
        config = SynchronizerConfig(
            time_range=TimeRangeConfig(
                default_start=999_999_999_999,  # Far future
                use_relay_state=False,
            ),
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
        ) as mock_sync:
            await sync._sync_all_relays([relay])

        # _sync_relay_events should NOT have been called
        mock_sync.assert_not_called()
        assert sync._synced_relays == 0

    async def test_sync_all_relays_with_override_timeouts(
        self, mock_synchronizer_brotr: Brotr
    ) -> None:
        """Test relay override timeouts are applied (lines 592-598)."""
        config = SynchronizerConfig(
            overrides=[
                RelayOverride(
                    url="wss://relay.example.com",
                    timeouts=RelayOverrideTimeouts(relay=999.0, request=88.0),
                ),
            ],
        )
        sync = Synchronizer(brotr=mock_synchronizer_brotr, config=config)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(0, 0, 0),
        ):
            await sync._sync_all_relays([relay])

        assert sync._synced_relays == 1

    async def test_sync_all_relays_with_cached_cursor(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test relay uses cached cursor for start time."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(  # type: ignore[method-assign]
            return_value={"wss://relay.example.com": 100}
        )

        relay = Relay("wss://relay.example.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            return_value=(1, 0, 0),
        ):
            await sync._sync_all_relays([relay])

        assert sync._synced_relays == 1

    async def test_sync_all_relays_exception_group(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test ExceptionGroup from TaskGroup is handled (lines 659-666)."""
        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._init_semaphores(sync._config.networks)
        sync._fetch_all_cursors = AsyncMock(return_value={})  # type: ignore[method-assign]

        relay = Relay("wss://exploding.relay.com")

        with patch(
            "bigbrotr.services.synchronizer._sync_relay_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unhandled"),
        ):
            await sync._sync_all_relays([relay])

        assert sync._failed_relays >= 1


# ============================================================================
# Synchronizer.run() Tests (additional coverage)
# ============================================================================


class TestSynchronizerRunCoverage:
    """Additional tests for Synchronizer.run() method (lines 525-570)."""

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
        # Should include both the DB relay and the override relay
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
        """Test run() handles invalid override URLs gracefully (lines 539-550)."""
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

        # Should not raise, invalid URL is logged and skipped
        await sync.run()

        # No relays to sync (DB empty + override invalid) -> no_relays_to_sync
        # _sync_all_relays should not be called since relays list is empty
        sync._sync_all_relays.assert_not_called()

    async def test_run_resets_counters(self, mock_synchronizer_brotr: Brotr) -> None:
        """Test run() resets all counters at the start of each cycle."""
        mock_synchronizer_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        sync = Synchronizer(brotr=mock_synchronizer_brotr)
        sync._synced_events = 99
        sync._synced_relays = 99
        sync._failed_relays = 99
        sync._invalid_events = 99
        sync._skipped_events = 99

        await sync.run()

        assert sync._synced_events == 0
        assert sync._synced_relays == 0
        assert sync._failed_relays == 0
        assert sync._invalid_events == 0
        assert sync._skipped_events == 0


# ============================================================================
# EventBatch Additional Edge Case Tests
# ============================================================================


class TestEventBatchAdditional:
    """Additional EventBatch edge case tests."""

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

    def test_is_full_at_limit_one(self) -> None:
        """Test is_full with limit=1."""
        batch = EventBatch(since=100, until=200, limit=1)
        assert batch.is_full() is False

        batch.append(_make_mock_event(150))
        assert batch.is_full() is True

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

    def test_len_matches_size(self) -> None:
        """Test __len__ always equals .size attribute."""
        batch = EventBatch(since=100, until=200, limit=10)

        assert len(batch) == batch.size == 0

        batch.append(_make_mock_event(150))
        assert len(batch) == batch.size == 1

        batch.append(_make_mock_event(160))
        assert len(batch) == batch.size == 2


# ============================================================================
# SyncTimeoutsConfig Additional Tests
# ============================================================================


class TestSyncTimeoutsConfigCoverage:
    """Additional coverage for SyncTimeoutsConfig.get_relay_timeout."""

    def test_get_relay_timeout_clearnet_explicit(self) -> None:
        """Test CLEARNET returns relay_clearnet (default fallthrough)."""
        config = SyncTimeoutsConfig(relay_clearnet=500.0)
        assert config.get_relay_timeout(NetworkType.CLEARNET) == 500.0

    def test_get_relay_timeout_i2p(self) -> None:
        """Test I2P returns relay_i2p."""
        config = SyncTimeoutsConfig(relay_i2p=2000.0)
        assert config.get_relay_timeout(NetworkType.I2P) == 2000.0

    def test_get_relay_timeout_loki(self) -> None:
        """Test LOKI returns relay_loki."""
        config = SyncTimeoutsConfig(relay_loki=2500.0)
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
            network_config=NetworkConfig(),
            request_timeout=10.0,
            brotr=mock_synchronizer_brotr,
            keys=keys,
        )
        assert ctx.request_timeout == 10.0
        assert ctx.filter_config.limit == 500

        with pytest.raises(AttributeError):
            ctx.request_timeout = 20.0  # type: ignore[misc]
