"""Synchronizer service utility functions.

Module-level sync algorithm, event batch management, and shared state types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from nostr_sdk import (
    Alphabet,
    Filter,
    Kind,
    SingleLetterTag,
    Timestamp,
)

from bigbrotr.core.logger import format_kv_pairs
from bigbrotr.models import Event, EventRelay

from .queries import insert_event_relays


if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator, Iterator

    from nostr_sdk import Client
    from nostr_sdk import Event as NostrEvent

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.models.service_state import ServiceState

    from .configs import FilterConfig


_logger = logging.getLogger(__name__)


def _log(level: str, message: str, **kwargs: Any) -> None:
    """Log a structured message with key=value pairs.

    Uses the module-level logger with format_kv_pairs for consistency
    with the main Logger class output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        message: Log message identifier.
        **kwargs: Additional key=value pairs appended to the message.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if _logger.isEnabledFor(log_level):
        formatted = message + format_kv_pairs(kwargs, max_value_length=None)
        _logger.log(log_level, formatted)


class EventBatch:
    """Bounded container for Nostr events within a time interval.

    Collects events whose ``created_at`` falls within ``[since, until]``
    and tracks min/max timestamps. Raises ``OverflowError`` if the batch
    limit is exceeded.

    Attributes:
        since: Inclusive lower bound timestamp.
        until: Inclusive upper bound timestamp.
        limit: Maximum number of events allowed.
        size: Current event count.
        events: Collected ``NostrEvent`` objects.
        min_created_at: Earliest ``created_at`` in the batch (or ``None``
            if empty).
        max_created_at: Latest ``created_at`` in the batch (or ``None``
            if empty).

    See Also:
        ``_insert_batch``:
            Validates and persists batch contents to the database.
    """

    __slots__ = ("events", "limit", "max_created_at", "min_created_at", "since", "size", "until")

    def __init__(self, since: int, until: int, limit: int) -> None:
        self.since = since
        self.until = until
        self.limit = limit
        self.size = 0
        self.events: list[NostrEvent] = []
        self.min_created_at: int | None = None
        self.max_created_at: int | None = None

    def append(self, event: NostrEvent) -> None:
        """Add an event if its timestamp is within [since, until].

        Args:
            event: NostrEvent to add.

        Raises:
            OverflowError: If the batch has reached its size limit.
        """
        created_at = event.created_at().as_secs()

        if created_at < self.since or created_at > self.until:
            return

        if self.size >= self.limit:
            raise OverflowError("Batch limit reached")

        self.events.append(event)
        self.size += 1

        if self.min_created_at is None or created_at < self.min_created_at:
            self.min_created_at = created_at
        if self.max_created_at is None or created_at > self.max_created_at:
            self.max_created_at = created_at

    def is_full(self) -> bool:
        """Check if batch has reached its limit."""
        return self.size >= self.limit

    def is_empty(self) -> bool:
        """Check if batch contains no events."""
        return self.size == 0

    def __len__(self) -> int:
        """Return the number of events in the batch."""
        return self.size

    def __iter__(self) -> Iterator[NostrEvent]:
        """Iterate over events in the batch."""
        return iter(self.events)


def create_filter(since: int, until: int, config: FilterConfig) -> Filter:
    """Build a nostr-sdk ``Filter`` from the given time range and filter configuration.

    Supports standard fields (``ids``, ``kinds``, ``authors``) and tag
    filters specified as ``{tag_letter: [values]}`` (e.g.,
    ``{"e": ["event_id"], "t": ["hashtag"]}``).

    See Also:
        [FilterConfig][bigbrotr.services.synchronizer.FilterConfig]:
            The configuration model consumed by this function.
    """
    f = (
        Filter()
        .since(Timestamp.from_secs(since))
        .until(Timestamp.from_secs(until))
        .limit(config.limit)
    )

    if config.kinds:
        f = f.kinds([Kind(k) for k in config.kinds])
    if config.authors:
        f = f.authors(config.authors)
    if config.ids:
        f = f.ids(config.ids)

    # Tag filters: {"tag_letter": ["value1", "value2"], ...}
    if config.tags:
        for tag_letter, values in config.tags.items():
            if not values:
                continue

            if len(tag_letter) == 1 and tag_letter.isalpha():
                try:
                    alphabet = getattr(Alphabet, tag_letter.upper())
                    tag = SingleLetterTag.lowercase(alphabet)
                    for value in values:
                        f = f.custom_tag(tag, value)
                except AttributeError:
                    # Invalid alphabet letter, skip
                    _log(
                        "WARNING",
                        "invalid_tag_filter",
                        tag=tag_letter,
                        reason="not a valid alphabet letter",
                    )

    return f


async def insert_batch(
    batch: EventBatch, relay: Relay, brotr: Brotr, since: int, until: int
) -> tuple[int, int]:
    """Validate and insert a batch of events into the database.

    Each event is verified for signature validity and timestamp range before
    insertion. Invalid events are counted but not inserted.

    Args:
        batch: [EventBatch][bigbrotr.services.synchronizer.EventBatch]
            containing nostr-sdk Events.
        relay: Source [Relay][bigbrotr.models.relay.Relay] for attribution.
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        since: Lower timestamp bound (events must be >= this).
        until: Upper timestamp bound (events must be <= this).

    Returns:
        Tuple of (events_inserted, events_invalid).

    Note:
        Events are inserted via the ``event_relay_insert_cascade`` stored
        procedure, which atomically inserts the event, relay, and
        junction record. The batch is split into sub-batches of
        ``brotr.config.batch.max_size`` for insertion.
    """
    if batch.is_empty():
        return 0, 0

    event_relays: list[EventRelay] = []
    invalid_count = 0

    for evt in batch:
        try:
            if not evt.verify():
                _log(
                    "WARNING",
                    "invalid_event_signature",
                    relay=relay.url,
                    event_id=evt.id().to_hex(),
                )
                invalid_count += 1
                continue

            # Validate timestamp range (relays may return out-of-range events)
            event_timestamp = evt.created_at().as_secs()
            if event_timestamp < since or event_timestamp > until:
                _log(
                    "WARNING",
                    "event_timestamp_out_of_range",
                    relay=relay.url,
                    event_id=evt.id().to_hex(),
                    event_ts=event_timestamp,
                    filter_since=since,
                    filter_until=until,
                )
                invalid_count += 1
                continue

            event_relays.append(EventRelay(Event(evt), relay))
        except (ValueError, TypeError, OverflowError) as e:
            _log("DEBUG", "event_parse_error", relay=relay.url, error=str(e))

    total_inserted = await insert_event_relays(brotr, event_relays)
    return total_inserted, invalid_count


@dataclass(slots=True)
class SyncBatchState:
    """Shared mutable cursor state across sync workers within a single cycle.

    Groups the lock and cursor update buffer used by
    [Synchronizer][bigbrotr.services.synchronizer.service.Synchronizer]
    workers running concurrently under a ``TaskGroup``.

    Note:
        Not frozen because ``cursor_updates`` is mutated under
        ``cursor_lock`` during concurrent processing.
    """

    cursor_updates: list[ServiceState]
    cursor_lock: asyncio.Lock
    cursor_flush_interval: int


async def iter_relay_events(
    client: Client,
    start_time: int,
    end_time: int,
    filter_config: FilterConfig,
    request_timeout: float,
) -> AsyncIterator[EventBatch]:
    """Forward-progression sync algorithm yielding event batches in ascending time order.

    Uses a time-window stack with binary splitting to guarantee that all
    events in ``[start_time, end_time]`` are retrieved, even when the relay
    caps its response at ``filter_config.limit`` events per request.

    When a fetch returns ``limit`` events (indicating the relay may have
    truncated its response), the current window is split in half and the
    left (earlier) half is retried first. This ensures batches are always
    yielded in ascending time order, suitable for cursor-based resumption.

    Args:
        client: Connected nostr-sdk ``Client`` with the target relay added.
        start_time: Inclusive lower timestamp bound (since).
        end_time: Inclusive upper timestamp bound (until).
        filter_config: [FilterConfig][bigbrotr.services.synchronizer.FilterConfig]
            with limit, kinds, authors, and tag constraints.
        request_timeout: Seconds to wait for each ``fetch_events`` call.

    Yields:
        [EventBatch][bigbrotr.services.synchronizer.EventBatch] for each
        completed sub-window, in ascending time order. Each batch's
        ``since``/``until`` reflect the sub-window boundaries.
    """
    until_stack = [end_time]
    current_since = start_time

    while until_stack:
        current_until = until_stack[0]

        f = create_filter(current_since, current_until, filter_config)
        events = await client.fetch_events(f, timedelta(seconds=request_timeout))
        event_list = events.to_vec()

        if not event_list:
            until_stack.pop(0)
            current_since = current_until + 1
            continue

        batch = EventBatch(current_since, current_until, len(event_list))
        for evt in event_list:
            try:
                batch.append(evt)
            except OverflowError:
                break

        if batch.is_empty():
            until_stack.pop(0)
            current_since = current_until + 1
            continue

        if len(event_list) < filter_config.limit or current_since == current_until:
            yield batch
            until_stack.pop(0)
            current_since = current_until + 1
        else:
            mid = current_since + (current_until - current_since) // 2
            until_stack.insert(0, mid)
