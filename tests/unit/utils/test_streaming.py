"""Unit tests for utils.streaming module.

Tests:
- _to_domain_events() sorting and conversion
- _FetchContext frozen dataclass
- _fetch_validated() event fetching with validation
- _try_verify_completeness() data-driven verification
- stream_events() windowing algorithm
"""

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
            ):
                pass

        # Binary split should have been triggered
        assert call_count > 1
