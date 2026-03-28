"""Unit tests for utils.streaming module.

Tests:
- _to_domain_events() sorting and conversion
- _FetchContext frozen dataclass
- _fetch_validated() event fetching with validation
- _try_verify_completeness() data-driven verification
- stream_events() windowing algorithm
- stream_events() idle timeout
- _fetch_validated() recv timeout on stream.next()
"""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.utils.streaming import (
    _fetch_validated,
    _FetchContext,
    _to_domain_events,
    _try_verify_completeness,
    stream_events,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_raw_event(
    event_id: str = "a" * 64,
    created_at: int = 1700000000,
    *,
    verify_ok: bool = True,
) -> MagicMock:
    """Create a mock nostr_sdk.Event with minimal interface."""
    evt = MagicMock()
    mock_id = MagicMock()
    mock_id.to_hex.return_value = event_id
    mock_id.__hash__ = lambda _: hash(event_id)
    mock_id.__eq__ = lambda self, other: hash(self) == hash(other)
    evt.id.return_value = mock_id
    evt.created_at.return_value.as_secs.return_value = created_at
    evt.verify.return_value = verify_ok
    return evt


def _make_ctx(
    mock_client: MagicMock | None = None,
    filters: list[MagicMock] | None = None,
    limit: int = 100,
    fetch_timeout: float = 10.0,
) -> _FetchContext:
    """Create a _FetchContext with sensible defaults."""
    return _FetchContext(
        client=mock_client or MagicMock(),
        filters=filters or [MagicMock()],
        limit=limit,
        fetch_timeout=timedelta(seconds=fetch_timeout),
    )


# ============================================================================
# _to_domain_events Tests
# ============================================================================


class TestToDomainEvents:
    """Tests for _to_domain_events()."""

    def test_empty_list(self) -> None:
        assert _to_domain_events([]) == []

    def test_sorts_by_created_at_then_id(self) -> None:
        evt_b = _make_raw_event(event_id="b" * 64, created_at=100)
        evt_a = _make_raw_event(event_id="a" * 64, created_at=100)
        evt_c = _make_raw_event(event_id="c" * 64, created_at=50)

        with patch("bigbrotr.utils.streaming.Event") as MockEvent:
            MockEvent.side_effect = lambda e: e  # pass-through
            result = _to_domain_events([evt_b, evt_a, evt_c])

        # Sorted ascending: created_at=50 first, then created_at=100 with id a < b
        assert result[0] is evt_c
        assert result[1] is evt_a
        assert result[2] is evt_b

    def test_drops_invalid_events(self) -> None:
        good = _make_raw_event(event_id="a" * 64, created_at=100)
        bad = _make_raw_event(event_id="b" * 64, created_at=200)

        with patch("bigbrotr.utils.streaming.Event") as MockEvent:

            def side_effect(e: MagicMock) -> MagicMock:
                if e is bad:
                    raise ValueError("null bytes")
                return e

            MockEvent.side_effect = side_effect
            result = _to_domain_events([good, bad])

        assert len(result) == 1
        assert result[0] is good

    def test_drops_type_error(self) -> None:
        evt = _make_raw_event()
        with patch("bigbrotr.utils.streaming.Event", side_effect=TypeError("bad type")):
            result = _to_domain_events([evt])
        assert result == []

    def test_drops_overflow_error(self) -> None:
        evt = _make_raw_event()
        with patch("bigbrotr.utils.streaming.Event", side_effect=OverflowError("too big")):
            result = _to_domain_events([evt])
        assert result == []

    def test_drops_event_exceeding_max_size(self) -> None:
        evt = _make_raw_event()
        evt.as_json.return_value = "x" * 1001
        with patch("bigbrotr.utils.streaming.Event") as MockEvent:
            MockEvent.side_effect = lambda e: e
            result = _to_domain_events([evt], max_event_size=1000)
        assert result == []

    def test_accepts_event_within_max_size(self) -> None:
        evt = _make_raw_event()
        evt.as_json.return_value = "x" * 1000
        with patch("bigbrotr.utils.streaming.Event") as MockEvent:
            MockEvent.side_effect = lambda e: e
            result = _to_domain_events([evt], max_event_size=1000)
        assert len(result) == 1

    def test_no_size_filter_when_none(self) -> None:
        evt = _make_raw_event()
        with patch("bigbrotr.utils.streaming.Event") as MockEvent:
            MockEvent.side_effect = lambda e: e
            result = _to_domain_events([evt], max_event_size=None)
        assert len(result) == 1
        evt.as_json.assert_not_called()


# ============================================================================
# _FetchContext Tests
# ============================================================================


class TestFetchContext:
    """Tests for _FetchContext frozen dataclass."""

    def test_immutable(self) -> None:
        ctx = _make_ctx()
        with pytest.raises(FrozenInstanceError):
            ctx.limit = 50  # type: ignore[misc]

    def test_stores_fields(self) -> None:
        client = MagicMock()
        filters = [MagicMock()]
        ctx = _FetchContext(
            client=client,
            filters=filters,
            limit=200,
            fetch_timeout=timedelta(seconds=30),
        )
        assert ctx.client is client
        assert ctx.filters is filters
        assert ctx.limit == 200
        assert ctx.fetch_timeout == timedelta(seconds=30)


# ============================================================================
# _fetch_validated Tests
# ============================================================================


class TestFetchValidated:
    """Tests for _fetch_validated()."""

    async def test_returns_empty_when_no_events(self) -> None:
        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter

        mock_stream = AsyncMock()
        mock_stream.next.return_value = None

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter])
        result = await _fetch_validated(ctx, since=100, until=200, limit=10)
        assert result == []

    async def test_deduplicates_by_event_id(self) -> None:
        evt = _make_raw_event(event_id="a" * 64, created_at=100)

        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter
        mock_filter.match_event.return_value = True

        mock_stream = AsyncMock()
        # Return same event twice, then None
        mock_stream.next.side_effect = [evt, evt, None]

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter], limit=10)
        result = await _fetch_validated(ctx, since=100, until=200, limit=10)
        assert len(result) == 1

    async def test_skips_unverified_events(self) -> None:
        good = _make_raw_event(event_id="a" * 64, verify_ok=True)
        bad = _make_raw_event(event_id="b" * 64, verify_ok=False)

        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter
        mock_filter.match_event.return_value = True

        mock_stream = AsyncMock()
        mock_stream.next.side_effect = [bad, good, None]

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter], limit=10)
        result = await _fetch_validated(ctx, since=100, until=200, limit=10)
        assert len(result) == 1
        assert result[0] is good

    async def test_skips_non_matching_events(self) -> None:
        evt = _make_raw_event()

        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter
        mock_filter.match_event.return_value = False

        mock_stream = AsyncMock()
        mock_stream.next.side_effect = [evt, None]

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter], limit=10)
        result = await _fetch_validated(ctx, since=100, until=200, limit=10)
        assert result == []

    async def test_stream_next_timeout_breaks(self) -> None:
        """When stream.next() hangs, asyncio.wait_for breaks out."""
        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter

        async def hanging_next() -> None:
            await asyncio.sleep(999)

        mock_stream = MagicMock()
        mock_stream.next = hanging_next

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter], limit=10, fetch_timeout=0.05)
        result = await _fetch_validated(ctx, since=100, until=200, limit=10)
        assert result == []

    async def test_stops_at_limit(self) -> None:
        events = [_make_raw_event(event_id=f"{i:064x}", created_at=100 + i) for i in range(5)]

        mock_filter = MagicMock()
        mock_filter.since.return_value.until.return_value.limit.return_value = mock_filter
        mock_filter.match_event.return_value = True

        mock_stream = AsyncMock()
        mock_stream.next.side_effect = [*events, None]

        client = MagicMock()
        client.stream_events = AsyncMock(return_value=mock_stream)

        ctx = _make_ctx(mock_client=client, filters=[mock_filter], limit=3)
        result = await _fetch_validated(ctx, since=100, until=200, limit=3)
        assert len(result) == 3


# ============================================================================
# _try_verify_completeness Tests
# ============================================================================


class TestTryVerifyCompleteness:
    """Tests for _try_verify_completeness()."""

    async def test_returns_none_on_empty_boundary_fetch(self) -> None:
        evt = _make_raw_event(created_at=100)
        ctx = _make_ctx()

        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.return_value = []
            result = await _try_verify_completeness(ctx, [evt], current_since=50)

        assert result is None

    async def test_returns_none_on_inconsistent_max(self) -> None:
        evt = _make_raw_event(created_at=100)
        boundary = _make_raw_event(event_id="b" * 64, created_at=99)
        ctx = _make_ctx()

        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.return_value = [boundary]
            result = await _try_verify_completeness(ctx, [evt], current_since=50)

        assert result is None

    async def test_returns_none_when_probe_finds_earlier_events(self) -> None:
        evt = _make_raw_event(created_at=100)
        boundary = _make_raw_event(event_id="b" * 64, created_at=100)
        probe_evt = _make_raw_event(event_id="c" * 64, created_at=80)
        ctx = _make_ctx()

        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.side_effect = [[boundary], [probe_evt]]
            result = await _try_verify_completeness(ctx, [evt], current_since=50)

        assert result is None

    async def test_returns_combined_on_success(self) -> None:
        evt_above = _make_raw_event(event_id="a" * 64, created_at=150)
        evt_at_min = _make_raw_event(event_id="b" * 64, created_at=100)
        boundary = _make_raw_event(event_id="c" * 64, created_at=100)
        ctx = _make_ctx()

        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.side_effect = [[boundary], []]  # boundary fetch, probe (empty = no earlier events)
            result = await _try_verify_completeness(ctx, [evt_at_min, evt_above], current_since=50)

        assert result is not None
        assert len(result) == 2

    async def test_skips_probe_when_min_equals_since(self) -> None:
        """When min_ts == current_since, no probe is needed."""
        evt = _make_raw_event(event_id="a" * 64, created_at=50)
        boundary = _make_raw_event(event_id="b" * 64, created_at=50)
        ctx = _make_ctx()

        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.return_value = [boundary]
            result = await _try_verify_completeness(ctx, [evt], current_since=50)

        assert result is not None
        # Only one call (boundary fetch), no probe call
        assert mock.call_count == 1


# ============================================================================
# stream_events Tests
# ============================================================================


class TestStreamEvents:
    """Tests for stream_events() async generator."""

    async def test_start_after_end_yields_nothing(self) -> None:
        events = [
            evt
            async for evt in stream_events(
                client=MagicMock(),
                filters=[MagicMock()],
                start_time=200,
                end_time=100,
                limit=10,
                request_timeout=5.0,
                idle_timeout=60.0,
            )
        ]
        assert events == []

    async def test_yields_nothing_for_empty_window(self) -> None:
        with patch("bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock) as mock:
            mock.return_value = []
            events = [
                evt
                async for evt in stream_events(
                    client=MagicMock(),
                    filters=[MagicMock()],
                    start_time=100,
                    end_time=100,
                    limit=10,
                    request_timeout=5.0,
                    idle_timeout=60.0,
                )
            ]
        assert events == []

    async def test_single_second_window_yields_all(self) -> None:
        raw = _make_raw_event(event_id="a" * 64, created_at=100)
        domain_event = MagicMock()

        with (
            patch(
                "bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock
            ) as mock_fetch,
            patch("bigbrotr.utils.streaming._to_domain_events") as mock_convert,
        ):
            mock_fetch.return_value = [raw]
            mock_convert.return_value = [domain_event]

            events = [
                evt
                async for evt in stream_events(
                    client=MagicMock(),
                    filters=[MagicMock()],
                    start_time=100,
                    end_time=100,
                    limit=10,
                    request_timeout=5.0,
                    idle_timeout=60.0,
                )
            ]

        assert events == [domain_event]

    async def test_verified_window_yields_events(self) -> None:
        raw = _make_raw_event(event_id="a" * 64, created_at=100)
        domain_event = MagicMock()

        with (
            patch(
                "bigbrotr.utils.streaming._fetch_validated", new_callable=AsyncMock
            ) as mock_fetch,
            patch(
                "bigbrotr.utils.streaming._try_verify_completeness", new_callable=AsyncMock
            ) as mock_verify,
            patch("bigbrotr.utils.streaming._to_domain_events") as mock_convert,
        ):
            mock_fetch.return_value = [raw]
            mock_verify.return_value = [raw]
            mock_convert.return_value = [domain_event]

            events = [
                evt
                async for evt in stream_events(
                    client=MagicMock(),
                    filters=[MagicMock()],
                    start_time=50,
                    end_time=200,
                    limit=10,
                    request_timeout=5.0,
                    idle_timeout=60.0,
                )
            ]

        assert events == [domain_event]

    async def test_binary_split_on_failed_verification(self) -> None:
        """When verification fails, stream_events does binary split."""
        call_count = 0

        async def mock_fetch(ctx: _FetchContext, since: int, until: int, limit: int) -> list:
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return [_make_raw_event(created_at=since)]
            return []

        domain = MagicMock()

        with (
            patch("bigbrotr.utils.streaming._fetch_validated", side_effect=mock_fetch),
            patch(
                "bigbrotr.utils.streaming._try_verify_completeness",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("bigbrotr.utils.streaming._to_domain_events", return_value=[domain]),
        ):
            async for _ in stream_events(
                client=MagicMock(),
                filters=[MagicMock()],
                start_time=100,
                end_time=200,
                limit=10,
                request_timeout=5.0,
                idle_timeout=60.0,
            ):
                pass

        # Binary split should have been triggered
        assert call_count > 1

    async def test_idle_timeout_abandons_on_no_progress(self) -> None:
        """When idle_timeout expires without yields, stream exits."""
        fetch_count = 0

        async def slow_fetch(ctx: _FetchContext, since: int, until: int, limit: int) -> list:
            nonlocal fetch_count
            fetch_count += 1
            return []  # relay never returns events

        with patch("bigbrotr.utils.streaming._fetch_validated", side_effect=slow_fetch):
            # idle_timeout=0 means check triggers immediately on second iteration
            events = [
                evt
                async for evt in stream_events(
                    client=MagicMock(),
                    filters=[MagicMock()],
                    start_time=100,
                    end_time=200,
                    limit=10,
                    request_timeout=5.0,
                    idle_timeout=0.0,
                )
            ]

        assert events == []

    async def test_idle_timeout_resets_on_yield(self) -> None:
        """Idle timer resets each time an event is yielded."""
        raw_a = _make_raw_event(event_id="a" * 64, created_at=100)
        raw_b = _make_raw_event(event_id="b" * 64, created_at=101)

        async def fetch_by_window(ctx: _FetchContext, since: int, until: int, limit: int) -> list:
            # Single-second windows: return one event per second
            if since == 100 and until == 100:
                return [raw_a]
            if since == 101 and until == 101:
                return [raw_b]
            # Multi-second window: trigger binary split
            if since != until:
                return [raw_a]
            return []

        domain_a = MagicMock(name="domain_a")
        domain_b = MagicMock(name="domain_b")

        def mock_convert(raw_events: list, max_event_size: int | None = None) -> list:
            if raw_events and raw_events[0] is raw_a:
                return [domain_a]
            return [domain_b]

        with (
            patch("bigbrotr.utils.streaming._fetch_validated", side_effect=fetch_by_window),
            patch(
                "bigbrotr.utils.streaming._try_verify_completeness",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("bigbrotr.utils.streaming._to_domain_events", side_effect=mock_convert),
        ):
            events = [
                evt
                async for evt in stream_events(
                    client=MagicMock(),
                    filters=[MagicMock()],
                    start_time=100,
                    end_time=101,
                    limit=10,
                    request_timeout=5.0,
                    idle_timeout=10.0,
                )
            ]

        # Both events yielded — idle timer reset after first yield
        assert len(events) == 2


# ============================================================================
# stream_events Integration Tests (client-level mocks, full pipeline)
# ============================================================================

_integration_counter = 0


def _make_integration_event(created_at: int) -> MagicMock:
    """Create a mock event with auto-generated unique ID for integration tests."""
    global _integration_counter  # noqa: PLW0603
    _integration_counter += 1
    return _make_raw_event(event_id=f"{_integration_counter:064x}", created_at=created_at)


def _make_filter_mock() -> MagicMock:
    """Create a mock Filter that chains since/until/limit and matches all events."""
    f = MagicMock()
    f.since.return_value = f
    f.until.return_value = f
    f.limit.return_value = f
    f.match_event.return_value = True
    f.as_json.return_value = "{}"
    return f


def _make_stream(events: list[MagicMock]) -> AsyncMock:
    """Create a mock event stream that yields events then None."""
    iterator = iter([*events, None])
    stream = AsyncMock()
    stream.next = AsyncMock(side_effect=lambda: next(iterator))
    return stream


class TestStreamEventsIntegration:
    """Integration tests for stream_events exercising the full pipeline.

    These tests mock only the client (not internal functions), verifying
    windowing, verification, binary split, deduplication, and ordering
    end-to-end.
    """

    @pytest.fixture(autouse=True)
    def _bypass_event_model(self) -> None:  # type: ignore[misc]
        with patch("bigbrotr.utils.streaming.Event", side_effect=lambda x: x):
            yield

    async def test_empty_relay_yields_nothing(self) -> None:
        client = AsyncMock()
        client.stream_events = AsyncMock(return_value=_make_stream([]))
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0, 60.0)]

        assert events == []

    async def test_single_window_verified(self) -> None:
        evt200 = _make_integration_event(200)
        evt300 = _make_integration_event(300)
        evt400 = _make_integration_event(400)
        # Main [100, 1000]: 3 events → verify
        call1 = _make_stream([evt200, evt300, evt400])
        # Verify [100, 200]: event at min_ts=200
        call2 = _make_stream([evt200])
        # Probe [100, 199]: empty → complete
        call3 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0, 60.0)]

        assert len(events) == 3
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_at_limit_smart_path_yields_combined(self) -> None:
        # Main fetch: 3 events (== limit), min_ts=120
        call1 = _make_stream(
            [
                _make_integration_event(120),
                _make_integration_event(160),
                _make_integration_event(180),
            ]
        )
        # Verify fetch [100, 120]: events all at 120
        call2 = _make_stream([_make_integration_event(120)])
        # Probe [100, 119] with limit=1: empty
        call3 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 200, 3, 10.0, 60.0)]

        assert len(events) >= 3
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_inconsistent_verify_triggers_binary_split(self) -> None:
        evt120 = _make_integration_event(120)
        evt180 = _make_integration_event(180)
        # Main fetch [100, 200]: 2 events (== limit), min_ts=120
        call1 = _make_stream([evt120, evt180])
        # Verify fetch [100, 120]: returns event at 110 → inconsistent
        call2 = _make_stream([_make_integration_event(110)])
        # Binary split mid=150 → left half [100, 150]: 1 event at 120
        call3 = _make_stream([evt120])
        # Left verify [100, 120]: event at 120
        call4 = _make_stream([evt120])
        # Left probe [100, 119]: empty → complete
        call5 = _make_stream([])
        # Right half [151, 200]: 1 event at 180
        call6 = _make_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0, 60.0)]

        assert len(events) == 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_empty_verify_triggers_binary_split(self) -> None:
        evt150 = _make_integration_event(150)
        evt180 = _make_integration_event(180)
        # Main fetch [100, 200]: 2 events (== limit)
        call1 = _make_stream([evt150, evt180])
        # Verify fetch: empty → inconsistent → fallback
        call2 = _make_stream([])
        # Binary split mid=150 → left [100, 150]: 1 event at 150
        call3 = _make_stream([evt150])
        # Left verify [100, 150]: event at 150
        call4 = _make_stream([evt150])
        # Left probe [100, 149]: empty → complete
        call5 = _make_stream([])
        # Right [151, 200]: 1 event at 180
        call6 = _make_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0, 60.0)]

        assert len(events) == 2

    async def test_single_second_window_yields_all(self) -> None:
        evts = [_make_integration_event(500) for _ in range(3)]
        client = AsyncMock()
        client.stream_events = AsyncMock(return_value=_make_stream(evts))
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 500, 500, 3, 10.0, 60.0)]

        assert len(events) == 3

    async def test_ascending_order_within_window(self) -> None:
        evt200 = _make_integration_event(200)
        evt300 = _make_integration_event(300)
        evt400 = _make_integration_event(400)
        # Events in reverse order — should be sorted ascending
        call1 = _make_stream([evt400, evt200, evt300])
        # Verify [100, 200]: event at min_ts=200
        call2 = _make_stream([evt200])
        # Probe [100, 199]: empty → complete
        call3 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[call1, call2, call3])
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0, 60.0)]

        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == [200, 300, 400]

    async def test_multiple_filters_deduplicates(self) -> None:
        evt200 = _make_integration_event(200)
        evt300 = _make_integration_event(300)

        # Main fetch: filter1 → [200, 300], filter2 → [200, 300] (deduped)
        s1 = _make_stream([evt200, evt300])
        s2 = _make_stream([evt200, evt300])
        # Verify [100, 200]: filter1 → [200], filter2 → [200] (deduped)
        s3 = _make_stream([evt200])
        s4 = _make_stream([evt200])
        # Probe [100, 199]: filter1 → empty, filter2 → empty
        s5 = _make_stream([])
        s6 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=[s1, s2, s3, s4, s5, s6])
        filters = [_make_filter_mock(), _make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 1000, 500, 10.0, 60.0)]

        assert len(events) == 2

    async def test_exception_propagates(self) -> None:
        client = AsyncMock()
        client.stream_events = AsyncMock(side_effect=TimeoutError("fetch timeout"))
        filters = [_make_filter_mock()]

        with pytest.raises(TimeoutError, match="fetch timeout"):
            async for _ in stream_events(client, filters, 100, 1000, 500, 10.0, 60.0):
                pass

    async def test_partial_completion_on_exception(self) -> None:
        evt200 = _make_integration_event(200)
        # [100, 1000] limit=2: 2 events → at limit → verify
        call1 = _make_stream([evt200, _make_integration_event(800)])
        # Verify empty → inconsistent → binary split mid=550
        call2 = _make_stream([])
        # Left half [100, 550]: 1 event at 200
        call3 = _make_stream([evt200])
        # Left verify [100, 200]: event at 200
        call4 = _make_stream([evt200])
        # Left probe [100, 199]: empty → complete → yield
        call5 = _make_stream([])
        # Right half [551, 1000]: raises
        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, OSError("connection lost")]
        )
        filters = [_make_filter_mock()]

        events: list[MagicMock] = []
        with pytest.raises(OSError, match="connection lost"):
            async for e in stream_events(client, filters, 100, 1000, 2, 10.0, 60.0):
                events.append(e)

        assert len(events) == 1

    async def test_verify_min_differs_triggers_split(self) -> None:
        evt130 = _make_integration_event(130)
        evt180 = _make_integration_event(180)
        # Main fetch [100, 200]: 2 events (== limit), min_ts=150
        call1 = _make_stream([_make_integration_event(150), evt180])
        # Verify [100, 150]: returns event at 130 (verify_min != min_ts) → split
        call2 = _make_stream([evt130, _make_integration_event(150)])
        # Binary split mid=150 → left [100, 150]: 1 event at 130
        call3 = _make_stream([evt130])
        # Left verify [100, 130]: event at 130
        call4 = _make_stream([evt130])
        # Left probe [100, 129]: empty → complete
        call5 = _make_stream([])
        # Right [151, 200]: 1 event at 180
        call6 = _make_stream([evt180])
        # Right verify [151, 180]: event at 180
        call7 = _make_stream([evt180])
        # Right probe [151, 179]: empty → complete
        call8 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8]
        )
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 200, 2, 10.0, 60.0)]

        assert len(events) == 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)

    async def test_probe_finds_events_triggers_split(self) -> None:
        evt120 = _make_integration_event(120)
        evt150 = _make_integration_event(150)
        evt280 = _make_integration_event(280)
        # Main fetch [100, 300]: 3 events (== limit), min_ts=150
        call1 = _make_stream([evt150, _make_integration_event(200), evt280])
        # Verify [100, 150]: all at 150
        call2 = _make_stream([evt150])
        # Probe [100, 149] limit=1: finds event → earlier data exists → split
        call3 = _make_stream([evt120])
        # Binary split mid=200 → left [100, 200]: 2 events at 120, 150
        call4 = _make_stream([evt120, evt150])
        # Left verify [100, 120]: event at 120
        call5 = _make_stream([evt120])
        # Left probe [100, 119]: empty → complete
        call6 = _make_stream([])
        # Right [201, 300]: 1 event at 280
        call7 = _make_stream([evt280])
        # Right verify [201, 280]: event at 280
        call8 = _make_stream([evt280])
        # Right probe [201, 279]: empty → complete
        call9 = _make_stream([])

        client = AsyncMock()
        client.stream_events = AsyncMock(
            side_effect=[call1, call2, call3, call4, call5, call6, call7, call8, call9]
        )
        filters = [_make_filter_mock()]

        events = [e async for e in stream_events(client, filters, 100, 300, 3, 10.0, 60.0)]

        assert len(events) >= 2
        timestamps = [e.created_at().as_secs() for e in events]
        assert timestamps == sorted(timestamps)
