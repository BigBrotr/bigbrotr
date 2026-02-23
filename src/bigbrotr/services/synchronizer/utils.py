"""Synchronizer service utility functions.

Module-level sync logic, event batch management, and context types.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from nostr_sdk import (
    Alphabet,
    Filter,
    Kind,
    RelayUrl,
    SingleLetterTag,
    Timestamp,
)

from bigbrotr.core.logger import format_kv_pairs
from bigbrotr.models import Event, EventRelay
from bigbrotr.utils.protocol import create_client


if TYPE_CHECKING:
    from collections.abc import Iterator

    from nostr_sdk import Event as NostrEvent
    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.models.service_state import ServiceState
    from bigbrotr.services.common.configs import NetworksConfig

    from .configs import FilterConfig


# =============================================================================
# Logging
# =============================================================================

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


# =============================================================================
# Event Batch
# =============================================================================


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


# =============================================================================
# Filter Builder
# =============================================================================


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


# =============================================================================
# Batch Insertion
# =============================================================================


async def insert_batch(
    batch: EventBatch, relay: Relay, brotr: Brotr, since: int, until: int
) -> tuple[int, int, int]:
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
        Tuple of (events_inserted, events_invalid, events_skipped).

    Note:
        Events are inserted via the ``event_relay_insert_cascade`` stored
        procedure, which atomically inserts the event, relay, and
        junction record. The batch is split into sub-batches of
        ``brotr.config.batch.max_size`` for insertion.
    """
    if batch.is_empty():
        return 0, 0, 0

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

    total_inserted = 0

    if event_relays:
        batch_size = brotr.config.batch.max_size
        for i in range(0, len(event_relays), batch_size):
            inserted = await brotr.insert_event_relay(event_relays[i : i + batch_size])
            total_inserted += inserted

    return total_inserted, invalid_count, 0


# =============================================================================
# Sync State Types
# =============================================================================


@dataclass(slots=True)
class SyncCycleCounters:
    """Per-cycle synchronization counters.

    Groups relay/event outcome counts and the lock that guards
    concurrent updates from ``TaskGroup`` workers.

    See Also:
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]:
            Service that owns an instance of this dataclass.
    """

    synced_events: int = 0
    synced_relays: int = 0
    failed_relays: int = 0
    invalid_events: int = 0
    skipped_events: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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


@dataclass(frozen=True, slots=True)
class SyncContext:
    """Immutable context shared across all relay sync operations in a cycle.

    See Also:
        ``sync_relay_events``:
            The function that consumes this context.
    """

    filter_config: FilterConfig
    network_config: NetworksConfig
    request_timeout: float
    brotr: Brotr
    keys: Keys


# =============================================================================
# Core Sync Function
# =============================================================================


async def sync_relay_events(
    relay: Relay,
    start_time: int,
    end_time: int,
    ctx: SyncContext,
) -> tuple[int, int, int]:
    """Core sync algorithm: connect to a relay, fetch events, and insert into the database.

    Uses [create_client][bigbrotr.utils.protocol.create_client] to
    establish a WebSocket connection (with optional SOCKS5 proxy for
    overlay networks), fetches events matching the configured filter,
    and batch-inserts valid events.

    Args:
        relay: [Relay][bigbrotr.models.relay.Relay] to sync from.
        start_time: Inclusive start timestamp (since).
        end_time: Inclusive end timestamp (until).
        ctx: [SyncContext][bigbrotr.services.synchronizer.SyncContext]
            with filter, network, timeout, database, and key settings.

    Returns:
        Tuple of (events_synced, invalid_events, skipped_events).
    """
    events_synced = 0
    invalid_events = 0
    skipped_events = 0

    proxy_url = ctx.network_config.get_proxy_url(relay.network)
    client = await create_client(ctx.keys, proxy_url)
    await client.add_relay(RelayUrl.parse(relay.url))

    try:
        await client.connect()

        f = create_filter(start_time, end_time, ctx.filter_config)
        events = await client.fetch_events(f, timedelta(seconds=ctx.request_timeout))
        event_list = events.to_vec()

        if event_list:
            # Convert to batch format
            batch = EventBatch(start_time, end_time, len(event_list))
            for evt in event_list:
                try:
                    batch.append(evt)
                except OverflowError:
                    break

            events_synced, invalid_events, skipped_events = await insert_batch(
                batch, relay, ctx.brotr, start_time, end_time
            )

        await client.disconnect()
    except (TimeoutError, OSError) as e:
        _log("WARNING", "sync_relay_error", relay=relay.url, error=str(e))
    finally:
        # nostr-sdk client.shutdown() can raise arbitrary errors from the
        # Rust FFI layer during cleanup; suppress broadly in this finally block.
        with contextlib.suppress(Exception):
            await client.shutdown()

    return events_synced, invalid_events, skipped_events
