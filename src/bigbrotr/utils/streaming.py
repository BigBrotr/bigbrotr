"""Data-driven event streaming algorithm with binary-split fallback.

Provides ``stream_events`` — the core windowing algorithm that streams
Nostr events in ascending ``(created_at, id)`` order, ensuring
completeness even when a relay truncates responses.

``_fetch_validated`` is the single source of truth for event validation.
``stream_events`` orchestrates windowing, sorting, and domain conversion.

This module lives in ``bigbrotr.utils`` (not ``services``) because it has
no service-layer dependencies — only ``nostr_sdk`` and ``bigbrotr.models``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from nostr_sdk import Filter, Timestamp

from bigbrotr.models import Event


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nostr_sdk import Client
    from nostr_sdk import Event as NostrEvent


logger = logging.getLogger(__name__)


# ── Event conversion ──────────────────────────────────────────────


def _to_domain_events(raw_events: list[NostrEvent]) -> list[Event]:
    """Sort raw events and convert to domain models.

    Sorts by ascending ``(created_at, id)`` then wraps each ``NostrEvent``
    in an ``Event`` domain model. Events that fail model validation (null
    bytes, overflow) are silently dropped with a debug log.
    """
    raw_events.sort(key=lambda e: (e.created_at().as_secs(), e.id().to_hex()))
    result: list[Event] = []
    for evt in raw_events:
        try:
            result.append(Event(evt))
        except (ValueError, TypeError, OverflowError) as e:
            logger.debug("event_parse_error error=%s", e)
    return result


# ── Sync algorithm ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _FetchContext:
    """Immutable context shared across fetch operations within a sync session."""

    client: Client
    filters: list[Filter]
    limit: int
    fetch_timeout: timedelta


async def _fetch_validated(
    ctx: _FetchContext, since: int, until: int, limit: int
) -> list[NostrEvent]:
    """Fetch events from all filters via streaming with full validation.

    Single source of truth for all event validation in the sync pipeline.
    Every event returned satisfies all four guarantees:

    1. **Filtered** — passes ``Filter.match_event()`` (kinds, authors, tags, time range).
    2. **Verified** — valid cryptographic signature (``Event.verify()``).
    3. **Deduplicated** — unique by ``EventId`` across all filters.
    4. **Limited** — at most ``limit`` events returned; streaming stops early.

    Events are returned in **arbitrary order**. Sorting and domain model
    conversion happen at the yield boundary in ``stream_events``.

    Uses ``stream_events`` (not ``fetch_events``) to consume events one at a
    time, preventing relay flooding when responses exceed the requested limit.
    """
    events: list[NostrEvent] = []
    seen_ids: set[object] = set()
    since_ts = Timestamp.from_secs(since)
    until_ts = Timestamp.from_secs(until)

    for base in ctx.filters:
        windowed = base.since(since_ts).until(until_ts).limit(limit)
        stream = await ctx.client.stream_events(windowed, ctx.fetch_timeout)
        while len(events) < limit:
            evt = await stream.next()
            if evt is None:
                break
            if not windowed.match_event(evt) or not evt.verify():
                continue
            eid = evt.id()
            if eid not in seen_ids:
                seen_ids.add(eid)
                events.append(evt)
        if len(events) >= limit:
            break

    return events


async def _try_verify_completeness(
    ctx: _FetchContext,
    events: list[NostrEvent],
    current_since: int,
) -> list[NostrEvent] | None:
    """Attempt data-driven verification when a fetch hits the limit.

    Input events may be in any order — only ``min(created_at)`` is used.
    The combined result is unordered; ``stream_events`` sorts before
    yielding.

    Returns the combined event list on success, or ``None`` to signal
    that the caller should fall back to binary split.
    """
    min_ts = min(e.created_at().as_secs() for e in events)

    boundary_events = await _fetch_validated(ctx, current_since, min_ts, ctx.limit)

    if not boundary_events:
        logger.debug("inconsistent_relay_empty_verify")
        return None

    boundary_max = max(e.created_at().as_secs() for e in boundary_events)
    if boundary_max != min_ts:
        logger.debug("inconsistent_relay_verify_max expected=%s got=%s", min_ts, boundary_max)
        return None

    boundary_min = min(e.created_at().as_secs() for e in boundary_events)
    if boundary_min != min_ts:
        return None

    # All boundary events are at min_ts. Probe for events before min_ts.
    if min_ts > current_since:
        probe = await _fetch_validated(ctx, current_since, min_ts - 1, 1)
        if probe:
            return None

    # Combine: boundary events at min_ts + original events above min_ts.
    # Dedup by EventId across both sets. Order is arbitrary — caller sorts.
    above_min = {evt.id(): evt for evt in events if evt.created_at().as_secs() != min_ts}
    at_min = {evt.id(): evt for evt in boundary_events}
    return [*at_min.values(), *above_min.values()]


async def stream_events(  # noqa: PLR0913
    client: Client,
    filters: list[Filter],
    start_time: int,
    end_time: int,
    limit: int,
    request_timeout: float,
) -> AsyncIterator[Event]:
    """Stream all events matching ``filters`` in ``[start_time, end_time]``,
    yielded as domain ``Event`` objects in ascending ``(created_at, id)`` order.

    Uses a data-driven windowing algorithm for completeness: when a fetch
    returns ``limit`` events (possible truncation), a verification re-fetch
    at ``min_created_at`` determines whether all events have been captured.
    Falls back to binary-split windowing on inconsistent relay responses.

    Validation (filter matching, signature verification, deduplication) is
    handled by ``_fetch_validated``. This function orchestrates windowing, then
    sorts and converts raw events to domain ``Event`` models at each yield
    boundary via ``_to_domain_events``.

    Args:
        client: Connected nostr-sdk ``Client`` with the target relay added.
        filters: Pre-validated base ``Filter`` objects **without**
            ``since``/``until``/``limit`` (use
            ``SynchronizerConfig.filters``).
        start_time: Inclusive lower timestamp bound (since).
        end_time: Inclusive upper timestamp bound (until).
        limit: Max events per relay request (REQ limit).
        request_timeout: Seconds to wait for each ``stream_events`` call.

    Yields:
        Domain ``Event`` objects in ascending ``(created_at, id)`` order.
    """
    if start_time > end_time:
        return

    ctx = _FetchContext(
        client=client,
        filters=filters,
        limit=limit,
        fetch_timeout=timedelta(seconds=request_timeout),
    )
    until_stack = [end_time]
    current_since = start_time

    while until_stack:
        current_until = until_stack[0]

        events = await _fetch_validated(ctx, current_since, current_until, limit)

        if not events:
            until_stack.pop(0)
            current_since = current_until + 1
            continue

        # Single-second window: cannot split further, yield everything.
        if current_since == current_until:
            for evt in _to_domain_events(events):
                yield evt
            until_stack.pop(0)
            current_since = current_until + 1
            continue

        # Multi-second window: always verify completeness. A relay may
        # enforce its own limit lower than ours, returning fewer events
        # even when more exist in the window.
        verified = await _try_verify_completeness(ctx, events, current_since)

        if verified is not None:
            for evt in _to_domain_events(verified):
                yield evt
            until_stack.pop(0)
            current_since = current_until + 1
        else:
            mid = current_since + (current_until - current_since) // 2
            until_stack.insert(0, mid)
