"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Uses ``asyncio.TaskGroup`` with per-network semaphores for structured, bounded concurrency.

The synchronization workflow proceeds as follows:

1. Fetch relays from the database via
   [get_all_relays][bigbrotr.services.common.queries.get_all_relays]
   (optionally filtered by metadata age).
2. Load per-relay sync cursors from ``service_state`` via
   [get_all_service_cursors][bigbrotr.services.common.queries.get_all_service_cursors].
3. Connect to each relay and fetch events since the last sync timestamp.
4. Validate event signatures and timestamps before insertion.
5. Update per-relay cursors for the next cycle.

Note:
    Cursor-based pagination ensures each relay is synced incrementally.
    The cursor (``last_synced_at``) is stored as a
    [ServiceState][bigbrotr.models.service_state.ServiceState] record
    with ``state_type='cursor'``. Cursor updates are batched (flushed
    every ``cursor_flush_interval`` relays) for crash resilience.

    The stagger delay (``concurrency.stagger_delay``) randomizes the
    relay processing order to avoid thundering-herd effects when multiple
    synchronizer instances run concurrently.

See Also:
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
        Configuration model for networks, filters, time ranges,
        concurrency, and relay overrides.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for event
        insertion and cursor management.
    [Monitor][bigbrotr.services.monitor.Monitor]: Upstream service that
        health-checks the relays synced here.
    [Finder][bigbrotr.services.finder.Finder]: Downstream consumer that
        discovers relay URLs from the events collected here.
    [create_client][bigbrotr.utils.transport.create_client]: Factory for
        the nostr-sdk client used for WebSocket connections.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Synchronizer

    brotr = Brotr.from_yaml("config/brotr.yaml")
    sync = Synchronizer.from_yaml("config/services/synchronizer.yaml", brotr=brotr)

    async with brotr:
        async with sync:
            await sync.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg
from nostr_sdk import (
    Alphabet,
    Filter,
    Keys,
    Kind,
    RelayUrl,
    SingleLetterTag,
    Timestamp,
)
from nostr_sdk import (
    Event as NostrEvent,
)
from pydantic import BaseModel, Field, field_validator

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.core.logger import format_kv_pairs
from bigbrotr.models import Event, EventRelay, Relay
from bigbrotr.models.constants import EVENT_KIND_MAX, NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.utils.keys import KeysConfig
from bigbrotr.utils.transport import create_client

from .common.configs import NetworkConfig
from .common.mixins import NetworkSemaphoreMixin
from .common.queries import get_all_relays, get_all_service_cursors


# =============================================================================
# Constants
# =============================================================================

_HEX_STRING_LENGTH = 64

_logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from collections.abc import Iterator

    from bigbrotr.core.brotr import Brotr

# =============================================================================
# Utilities
# =============================================================================


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


class FilterConfig(BaseModel):
    """Nostr event filter configuration for sync subscriptions.

    See Also:
        ``_create_filter``:
            Converts this config into a nostr-sdk ``Filter`` object.
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    ids: list[str] | None = Field(default=None, description="Event IDs to sync (None = all)")
    kinds: list[int] | None = Field(default=None, description="Event kinds to sync (None = all)")
    authors: list[str] | None = Field(default=None, description="Authors to sync (None = all)")
    tags: dict[str, list[str]] | None = Field(default=None, description="Tag filters (None = all)")
    limit: int = Field(default=500, ge=1, le=5000, description="Events per request")

    @field_validator("kinds", mode="after")
    @classmethod
    def validate_kinds(cls, v: list[int] | None) -> list[int] | None:
        """Validate that all event kinds are within the valid range (0-65535)."""
        if v is None:
            return v
        for kind in v:
            if not 0 <= kind <= EVENT_KIND_MAX:
                raise ValueError(f"Event kind {kind} out of valid range (0-{EVENT_KIND_MAX})")
        return v

    @field_validator("ids", "authors", mode="after")
    @classmethod
    def validate_hex_strings(cls, v: list[str] | None) -> list[str] | None:
        """Validate that all entries are valid 64-character hex strings."""
        if v is None:
            return v
        for hex_str in v:
            if len(hex_str) != _HEX_STRING_LENGTH:
                raise ValueError(
                    f"Invalid hex string length: {len(hex_str)} (expected {_HEX_STRING_LENGTH})"
                )
            try:
                bytes.fromhex(hex_str)
            except ValueError as e:
                raise ValueError(f"Invalid hex string: {hex_str}") from e
        return v


class TimeRangeConfig(BaseModel):
    """Time range configuration controlling the sync window boundaries.

    Note:
        When ``use_relay_state`` is ``True`` (the default), the sync
        start time is determined by the per-relay cursor plus one second
        (to avoid re-fetching the last event). When ``False``, all relays
        start from ``default_start``. The ``lookback_seconds`` parameter
        controls how far back from ``now()`` the sync window extends.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
        [get_all_service_cursors][bigbrotr.services.common.queries.get_all_service_cursors]:
            Fetches the per-relay cursor values used when
            ``use_relay_state`` is enabled.
    """

    default_start: int = Field(default=0, ge=0, description="Default start timestamp (0 = epoch)")
    use_relay_state: bool = Field(
        default=True, description="Use per-relay state for start timestamp"
    )
    lookback_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Lookback window in seconds (default: 86400 = 24 hours)",
    )


class SyncTimeoutsConfig(BaseModel):
    """Per-relay sync timeout limits by network type.

    These are the maximum total times allowed for syncing a single relay.
    The per-request WebSocket timeout comes from
    [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig].

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    relay_clearnet: float = Field(
        default=1800.0, ge=60.0, le=14_400.0, description="Max time per clearnet relay sync"
    )
    relay_tor: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per Tor relay sync"
    )
    relay_i2p: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per I2P relay sync"
    )
    relay_loki: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per Loki relay sync"
    )

    def get_relay_timeout(self, network: NetworkType) -> float:
        """Get the maximum sync duration for a relay on the given network."""
        if network == NetworkType.TOR:
            return self.relay_tor
        if network == NetworkType.I2P:
            return self.relay_i2p
        if network == NetworkType.LOKI:
            return self.relay_loki
        return self.relay_clearnet


class SyncConcurrencyConfig(BaseModel):
    """Concurrency settings for parallel relay connections.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    cursor_flush_interval: int = Field(
        default=50, ge=1, description="Flush cursor updates every N relays"
    )
    stagger_delay: tuple[int, int] = Field(
        default=(0, 60), description="Random delay range (min, max) seconds"
    )


class SourceConfig(BaseModel):
    """Configuration for selecting which relays to sync from.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
        [get_all_relays][bigbrotr.services.common.queries.get_all_relays]:
            Query used when ``from_database`` is ``True``.
    """

    from_database: bool = Field(default=True, description="Fetch relays from database")
    max_metadata_age: int = Field(
        default=43_200,
        ge=0,
        description="Only sync relays checked within N seconds",
    )
    require_readable: bool = Field(default=True, description="Only sync readable relays")


class RelayOverrideTimeouts(BaseModel):
    """Per-relay timeout overrides (None means use the network default)."""

    request: float | None = None
    relay: float | None = None


class RelayOverride(BaseModel):
    """Per-relay configuration overrides (e.g., for high-traffic relays)."""

    url: str
    timeouts: RelayOverrideTimeouts = Field(default_factory=RelayOverrideTimeouts)


class SynchronizerConfig(BaseServiceConfig):
    """Synchronizer service configuration.

    See Also:
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The
            service class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``log_level`` fields.
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig]:
            Per-network timeout and proxy settings.
        [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Nostr key management
            for NIP-42 authentication during event fetching.
    """

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    filter: FilterConfig = Field(default_factory=FilterConfig)
    time_range: TimeRangeConfig = Field(default_factory=TimeRangeConfig)
    sync_timeouts: SyncTimeoutsConfig = Field(default_factory=SyncTimeoutsConfig)
    concurrency: SyncConcurrencyConfig = Field(default_factory=SyncConcurrencyConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    overrides: list[RelayOverride] = Field(default_factory=list)


# =============================================================================
# Sync Logic (Module-Level Pure Functions)
# =============================================================================


def _create_filter(since: int, until: int, config: FilterConfig) -> Filter:
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


async def _insert_batch(
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


@dataclass(slots=True)
class _SyncBatchState:
    """Shared mutable state across sync workers within a single cycle.

    Groups the locks and cursor update buffer used by
    [_sync_single_relay][bigbrotr.services.synchronizer.Synchronizer._sync_single_relay]
    workers running concurrently under a ``TaskGroup``.

    Note:
        Not frozen because ``cursor_updates`` is mutated under
        ``cursor_lock`` during concurrent processing.
    """

    cursor_updates: list[ServiceState]
    cursor_lock: asyncio.Lock
    counter_lock: asyncio.Lock
    cursor_flush_interval: int


@dataclass(frozen=True, slots=True)
class SyncContext:
    """Immutable context shared across all relay sync operations in a cycle.

    See Also:
        ``_sync_relay_events``:
            The function that consumes this context.
    """

    filter_config: FilterConfig
    network_config: NetworkConfig
    request_timeout: float
    brotr: Brotr
    keys: Keys


async def _sync_relay_events(
    relay: Relay,
    start_time: int,
    end_time: int,
    ctx: SyncContext,
) -> tuple[int, int, int]:
    """Core sync algorithm: connect to a relay, fetch events, and insert into the database.

    Uses [create_client][bigbrotr.utils.transport.create_client] to
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
    client = create_client(ctx.keys, proxy_url)
    await client.add_relay(RelayUrl.parse(relay.url))

    try:
        await client.connect()

        f = _create_filter(start_time, end_time, ctx.filter_config)
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

            events_synced, invalid_events, skipped_events = await _insert_batch(
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


# =============================================================================
# Service
# =============================================================================


class Synchronizer(NetworkSemaphoreMixin, BaseService[SynchronizerConfig]):
    """Event synchronization service.

    Collects Nostr events from validated relays and stores them in the
    database. Uses ``asyncio.TaskGroup`` with per-network semaphores for
    structured, bounded concurrency.

    Each cycle fetches relays from the database, loads per-relay sync
    cursors from ``service_state``, connects to each relay to fetch events
    since the last sync, validates signatures and timestamps, batch-inserts
    events, and updates per-relay cursors for the next cycle.

    Note:
        The relay list is shuffled before processing to prevent all
        synchronizer instances from hitting the same relays in the same
        order, reducing thundering-herd effects. Relay overrides can
        customize per-relay timeouts for high-traffic relays.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Configuration model for this service.
        [Monitor][bigbrotr.services.monitor.Monitor]: Upstream service
            that health-checks relays before they are synced.
        [Finder][bigbrotr.services.finder.Finder]: Downstream consumer
            that discovers relay URLs from the events collected here.
        [get_all_service_cursors][bigbrotr.services.common.queries.get_all_service_cursors]:
            Pre-fetches all per-relay cursor values.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.SYNCHRONIZER
    CONFIG_CLASS: ClassVar[type[SynchronizerConfig]] = SynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: SynchronizerConfig | None = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: SynchronizerConfig
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        self._synced_events: int = 0
        self._synced_relays: int = 0
        self._failed_relays: int = 0
        self._invalid_events: int = 0
        self._skipped_events: int = 0

        self._keys: Keys = self._config.keys.keys  # For NIP-42 authentication

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
        self._init_semaphores(self._config.networks)
        cycle_start = time.monotonic()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0
        self._invalid_events = 0
        self._skipped_events = 0

        relays = await self._fetch_relays()

        # Merge configured relay overrides that are not already in the list
        known_urls = {str(r.url) for r in relays}
        for override in self._config.overrides:
            if override.url not in known_urls:
                try:
                    relay = Relay(override.url)
                    relays.append(relay)
                    known_urls.add(relay.url)
                except (ValueError, TypeError) as e:
                    self._logger.warning(
                        "parse_override_relay_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=override.url,
                    )

        if not relays:
            self._logger.info("no_relays_to_sync")
            return

        self._logger.info("sync_started", relay_count=len(relays))
        random.shuffle(relays)

        await self._sync_all_relays(relays)

        elapsed = time.monotonic() - cycle_start
        self._logger.info(
            "cycle_completed",
            synced_relays=self._synced_relays,
            failed_relays=self._failed_relays,
            synced_events=self._synced_events,
            invalid_events=self._invalid_events,
            skipped_events=self._skipped_events,
            duration=round(elapsed, 2),
        )

    async def _sync_all_relays(self, relays: list[Relay]) -> None:
        """Sync all relays concurrently using structured concurrency.

        Note:
            Uses ``asyncio.TaskGroup`` for structured concurrency with
            per-network semaphores (from
            [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin])
            to bound simultaneous WebSocket connections per network type.
            Cursor updates are batched in memory and flushed every
            ``cursor_flush_interval`` relays for crash resilience.
            A ``counter_lock`` protects shared counters for
            future-proofing against free-threaded Python.
        """
        cursors = await self._fetch_all_cursors()
        batch = _SyncBatchState(
            cursor_updates=[],
            cursor_lock=asyncio.Lock(),
            counter_lock=asyncio.Lock(),
            cursor_flush_interval=self._config.concurrency.cursor_flush_interval,
        )

        try:
            async with asyncio.TaskGroup() as tg:
                for relay in relays:
                    tg.create_task(self._sync_single_relay(relay, cursors, batch))
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                self._logger.error(
                    "worker_unexpected_exception",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self._failed_relays += 1

        # Flush remaining cursor updates
        if batch.cursor_updates:
            try:
                await self._brotr.upsert_service_state(batch.cursor_updates)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "cursor_batch_upsert_failed",
                    error=str(e),
                    count=len(batch.cursor_updates),
                )

    async def _sync_single_relay(
        self, relay: Relay, cursors: dict[str, int], batch: _SyncBatchState
    ) -> None:
        """Sync events from a single relay with semaphore-bounded concurrency.

        Acquires the per-network semaphore, resolves timeouts (with per-relay
        overrides), fetches events via ``_sync_relay_events``, and updates
        shared counters and cursor buffer.

        Args:
            relay: Relay to sync from.
            cursors: Pre-fetched map of relay URL to last_synced_at timestamp.
            batch: Shared mutable state for cursor updates and locks.
        """
        semaphore = self._semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return

        async with semaphore:
            network_type_config = self._config.networks.get(relay.network)
            request_timeout = network_type_config.timeout
            relay_timeout = self._config.sync_timeouts.get_relay_timeout(relay.network)

            for override in self._config.overrides:
                if override.url == str(relay.url):
                    if override.timeouts.relay is not None:
                        relay_timeout = override.timeouts.relay
                    if override.timeouts.request is not None:
                        request_timeout = override.timeouts.request
                    break

            start = self._get_start_time_from_cache(relay, cursors)
            end_time = int(time.time()) - self._config.time_range.lookback_seconds
            if start >= end_time:
                return

            ctx = SyncContext(
                filter_config=self._config.filter,
                network_config=self._config.networks,
                request_timeout=request_timeout,
                brotr=self._brotr,
                keys=self._keys,
            )

            try:
                events_synced, invalid_events, skipped_events = await asyncio.wait_for(
                    _sync_relay_events(relay=relay, start_time=start, end_time=end_time, ctx=ctx),
                    timeout=relay_timeout,
                )

                async with batch.counter_lock:
                    self._synced_events += events_synced
                    self._invalid_events += invalid_events
                    self._skipped_events += skipped_events
                    self._synced_relays += 1

                async with batch.cursor_lock:
                    batch.cursor_updates.append(
                        ServiceState(
                            service_name=self.SERVICE_NAME,
                            state_type=ServiceStateType.CURSOR,
                            state_key=relay.url,
                            state_value={"last_synced_at": end_time},
                            updated_at=int(time.time()),
                        )
                    )
                    if len(batch.cursor_updates) >= batch.cursor_flush_interval:
                        await self._brotr.upsert_service_state(batch.cursor_updates.copy())
                        batch.cursor_updates.clear()

            except (TimeoutError, OSError, asyncpg.PostgresError) as e:
                self._logger.warning(
                    "relay_sync_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    url=relay.url,
                )
                async with batch.counter_lock:
                    self._failed_relays += 1

    async def _fetch_relays(self) -> list[Relay]:
        """Fetch validated relays from the database for synchronization.

        See Also:
            [get_all_relays][bigbrotr.services.common.queries.get_all_relays]:
                The SQL query executed by this method.
        """
        relays: list[Relay] = []

        if not self._config.source.from_database:
            return relays

        rows = await get_all_relays(self._brotr)

        for row in rows:
            url_str = row["url"].strip()
            try:
                relay = Relay(url_str, discovered_at=row["discovered_at"])
                relays.append(relay)
            except (ValueError, TypeError) as e:
                self._logger.debug("invalid_relay_url", url=url_str, error=str(e))

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def _fetch_all_cursors(self) -> dict[str, int]:
        """Batch-fetch all relay sync cursors in a single query.

        Returns:
            Dict mapping relay URL to ``last_synced_at`` timestamp.

        See Also:
            [get_all_service_cursors][bigbrotr.services.common.queries.get_all_service_cursors]:
                The SQL query executed by this method.
        """
        if not self._config.time_range.use_relay_state:
            return {}

        return await get_all_service_cursors(self._brotr, self.SERVICE_NAME, "last_synced_at")

    def _get_start_time_from_cache(self, relay: Relay, cursors: dict[str, int]) -> int:
        """Look up the sync start timestamp from a pre-fetched cursor cache.

        Args:
            relay: Relay to look up.
            cursors: Pre-fetched map of relay URL to last_synced_at.

        Returns:
            ``cursor + 1`` if found, otherwise ``time_range.default_start``.
        """
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        cursor = cursors.get(relay.url)
        if cursor is not None:
            return cursor + 1

        return self._config.time_range.default_start
