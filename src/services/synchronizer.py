"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Supports both single-process and multi-process modes (via aiomultiprocess)
for high-throughput event ingestion.

Workflow:
    1. Fetch relays from the database (optionally filtered by metadata age).
    2. Load per-relay sync cursors from the service_data table.
    3. Connect to each relay and fetch events since the last sync timestamp.
    4. Validate event signatures and timestamps before insertion.
    5. Update per-relay cursors for the next cycle.

Usage::

    from core import Brotr
    from services import Synchronizer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    sync = Synchronizer.from_yaml("yaml/services/synchronizer.yaml", brotr=brotr)

    async with brotr:
        async with sync:
            await sync.run_forever()
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import random
import signal
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import aiomultiprocess
from nostr_sdk import (
    Alphabet,
    Filter,
    Keys,
    Kind,
    SingleLetterTag,
    Timestamp,
)
from nostr_sdk import (
    Event as NostrEvent,
)
from pydantic import BaseModel, Field, field_validator

from core.base_service import BaseService, BaseServiceConfig
from core.brotr import Brotr
from models import Event, EventRelay, Relay
from models.constants import NetworkType
from utils.keys import KeysConfig

from .common.configs import NetworkConfig
from .common.constants import DataType, ServiceName
from .common.queries import get_all_relays, get_all_service_cursors


# =============================================================================
# Constants
# =============================================================================

_HEX_STRING_LENGTH = 64
_EVENT_KIND_MAX = 65_535


if TYPE_CHECKING:
    import logging
    from collections.abc import Iterator

# Worker processes cannot access class attributes, so these module-level
# globals provide logging configuration and state for forked processes.
_WORKER_SERVICE_NAME = ServiceName.SYNCHRONIZER
_WORKER_LOG_LEVEL = "INFO"  # Set by main process before spawning workers
_WORKER_LOGGER: logging.Logger | None = None  # Lazily created per worker


def _set_worker_log_level(level: str) -> None:
    """Set the log level for worker processes (must be called before spawning)."""
    global _WORKER_LOG_LEVEL  # noqa: PLW0603
    _WORKER_LOG_LEVEL = level.upper()


def _get_worker_logger() -> logging.Logger:
    """Get or lazily create a logger for the current worker process."""
    global _WORKER_LOGGER  # noqa: PLW0603
    if _WORKER_LOGGER is None:
        import logging  # noqa: PLC0415 - Worker process needs fresh import after fork
        import sys  # noqa: PLC0415 - Worker process needs fresh import after fork

        # Create worker-specific logger
        _WORKER_LOGGER = logging.getLogger(f"{_WORKER_SERVICE_NAME}.worker")

        # Only configure if no handlers exist (avoid duplicate handlers)
        if not _WORKER_LOGGER.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
                )
            )
            _WORKER_LOGGER.addHandler(handler)
            log_level = getattr(logging, _WORKER_LOG_LEVEL, logging.INFO)
            _WORKER_LOGGER.setLevel(log_level)
            # Prevent propagation to root logger
            _WORKER_LOGGER.propagate = False

    return _WORKER_LOGGER


def _format_kv(kwargs: dict[str, Any]) -> str:
    """Format kwargs as key=value pairs for worker log output.

    Delegates to the shared ``format_kv_pairs`` utility for consistency
    with the main Logger class. No value truncation in worker logs.
    """
    from core.logger import format_kv_pairs  # noqa: PLC0415 - Worker isolation

    return format_kv_pairs(kwargs, max_value_length=None)


def _worker_log(level: str, message: str, **kwargs: Any) -> None:
    """Log a message from a worker process.

    Initializes the worker logger on first call. Output format matches
    the main Logger class for consistent log parsing.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        message: Log message identifier.
        **kwargs: Additional key=value pairs appended to the message.
    """
    import logging  # noqa: PLC0415 - Worker isolation

    logger = _get_worker_logger()
    log_level = getattr(logging, level.upper(), logging.INFO)

    if logger.isEnabledFor(log_level):
        formatted = message + _format_kv(kwargs)
        logger.log(log_level, formatted)


# =============================================================================
# Utilities
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
        events: Collected NostrEvent objects.
        min_created_at: Earliest ``created_at`` in the batch (or None if empty).
        max_created_at: Latest ``created_at`` in the batch (or None if empty).
    """

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
    """Nostr event filter configuration for sync subscriptions."""

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
            if not 0 <= kind <= _EVENT_KIND_MAX:
                raise ValueError(f"Event kind {kind} out of valid range (0-{_EVENT_KIND_MAX})")
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
    """Time range configuration controlling the sync window boundaries."""

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
    The per-request WebSocket timeout comes from ``NetworkConfig``.
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


class ConcurrencyConfig(BaseModel):
    """Concurrency settings for parallel relay connections and worker processes."""

    max_parallel: int = Field(
        default=10, ge=1, le=100, description="Max concurrent relay connections per process"
    )
    max_processes: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    cursor_flush_interval: int = Field(
        default=50, ge=1, description="Flush cursor updates every N relays"
    )
    stagger_delay: tuple[int, int] = Field(
        default=(0, 60), description="Random delay range (min, max) seconds"
    )


class SourceConfig(BaseModel):
    """Configuration for selecting which relays to sync from."""

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
    """Synchronizer service configuration."""

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    filter: FilterConfig = Field(default_factory=FilterConfig)
    time_range: TimeRangeConfig = Field(default_factory=TimeRangeConfig)
    sync_timeouts: SyncTimeoutsConfig = Field(default_factory=SyncTimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    overrides: list[RelayOverride] = Field(default_factory=list)
    worker_log_level: str = Field(
        default="INFO",
        description="Log level for worker processes (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )


# =============================================================================
# Worker Logic (Pure Functions for Multiprocessing)
# =============================================================================

# Per-worker-process database connection (lazily initialized, shared across tasks)
_WORKER_BROTR: Brotr | None = None
_WORKER_CLEANUP_REGISTERED: bool = False
_WORKER_BROTR_LOCK: asyncio.Lock | None = None


def _get_worker_lock() -> asyncio.Lock:
    """Get or lazily create the asyncio.Lock for worker Brotr initialization."""
    global _WORKER_BROTR_LOCK  # noqa: PLW0603
    if _WORKER_BROTR_LOCK is None:
        _WORKER_BROTR_LOCK = asyncio.Lock()
    return _WORKER_BROTR_LOCK


def _reset_worker_state() -> None:
    """Reset all worker globals to initial state (used for test isolation)."""
    global _WORKER_BROTR, _WORKER_CLEANUP_REGISTERED, _WORKER_BROTR_LOCK  # noqa: PLW0603
    _WORKER_BROTR = None
    _WORKER_CLEANUP_REGISTERED = False
    _WORKER_BROTR_LOCK = None


def _cleanup_worker_brotr() -> None:
    """Close the worker's database connection on process termination.

    Registered via ``atexit`` and signal handlers for reliable cleanup.
    """
    global _WORKER_BROTR  # noqa: PLW0603
    if _WORKER_BROTR is not None:
        # Best effort cleanup - don't raise during process termination
        with contextlib.suppress(Exception):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_WORKER_BROTR.close())
            finally:
                loop.close()
        _WORKER_BROTR = None


def _signal_handler(signum: int, _frame: Any) -> None:
    """Signal handler that ensures database cleanup before worker exit."""
    _cleanup_worker_brotr()
    # Re-raise with default handler for proper exit code
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


async def _get_worker_brotr(brotr_config: dict[str, Any]) -> Brotr:
    """Get or initialize the per-worker-process Brotr database connection.

    Uses double-check locking to prevent race conditions when multiple
    async tasks within the same worker call this concurrently. The
    connection is reused across all tasks and cleaned up on exit.
    """
    global _WORKER_BROTR, _WORKER_CLEANUP_REGISTERED  # noqa: PLW0603

    # Fast path: return existing connection without lock
    if _WORKER_BROTR is not None:
        return _WORKER_BROTR

    # Slow path: acquire lock and double-check before initializing
    async with _get_worker_lock():
        # Re-check after acquiring lock (another task may have initialized)
        if _WORKER_BROTR is None:
            _WORKER_BROTR = Brotr.from_dict(brotr_config)
            await _WORKER_BROTR.connect()

            # Register cleanup handlers only once per worker process
            if not _WORKER_CLEANUP_REGISTERED:
                atexit.register(_cleanup_worker_brotr)
                # Also handle signals for more reliable cleanup
                try:
                    signal.signal(signal.SIGTERM, _signal_handler)
                    signal.signal(signal.SIGINT, _signal_handler)
                except (ValueError, OSError):
                    # Signal handlers can only be set from main thread
                    pass
                _WORKER_CLEANUP_REGISTERED = True

    return _WORKER_BROTR


async def sync_relay_task(
    relay_url: str,
    start_time: int,
    config_dict: dict[str, Any],
    brotr_config: dict[str, Any],
) -> tuple[str, int, int, int, int, bool]:
    """Sync events from a single relay (designed for worker processes).

    Args:
        relay_url: Relay WebSocket URL.
        start_time: Sync window start timestamp (since).
        config_dict: Serialized SynchronizerConfig for cross-process transfer.
        brotr_config: Serialized Brotr config for worker DB initialization.

    Returns:
        Tuple of (relay_url, events_synced, invalid_events, skipped_events,
        new_end_time, success). Success is True if sync completed (even with
        zero events), False on error or timeout.
    """
    try:
        # Reconstruct objects that cannot be pickled across process boundaries
        relay = Relay(relay_url)
        config = SynchronizerConfig(**config_dict)
        keys: Keys = config.keys.keys

        network_type_config = config.networks.get(relay.network)
        request_timeout = network_type_config.timeout
        relay_timeout = config.sync_timeouts.get_relay_timeout(relay.network)

        for override in config.overrides:
            if override.url == str(relay.url):
                if override.timeouts.relay is not None:
                    relay_timeout = override.timeouts.relay
                if override.timeouts.request is not None:
                    request_timeout = override.timeouts.request
                break

        brotr = await _get_worker_brotr(brotr_config)
        end_time = int(time.time()) - config.time_range.lookback_seconds

        if start_time >= end_time:
            return relay.url, 0, 0, 0, start_time, True  # No work needed, still success

        events_synced = 0
        invalid_events = 0
        skipped_events = 0

        ctx = SyncContext(
            filter_config=config.filter,
            network_config=config.networks,
            request_timeout=request_timeout,
            brotr=brotr,
            keys=keys,
        )

        async def _sync_with_client() -> tuple[int, int, int]:
            """Inner coroutine for wait_for timeout."""
            return await _sync_relay_events(
                relay=relay, start_time=start_time, end_time=end_time, ctx=ctx
            )

        try:
            events_synced, invalid_events, skipped_events = await asyncio.wait_for(
                _sync_with_client(), timeout=relay_timeout
            )

            if events_synced > 0:
                _worker_log(
                    "INFO",
                    "sync_ok",
                    relay=relay.url,
                    events=events_synced,
                    invalid=invalid_events,
                    skipped=skipped_events,
                )
            return relay.url, events_synced, invalid_events, skipped_events, end_time, True

        except TimeoutError:
            _worker_log("WARNING", "sync_timeout", relay=relay.url)
            return relay.url, events_synced, invalid_events, skipped_events, start_time, False
        except Exception as e:
            _worker_log("WARNING", "sync_error", relay=relay.url, error=str(e))
            return relay.url, events_synced, invalid_events, skipped_events, start_time, False

    except Exception as e:
        _worker_log("ERROR", "worker_init_error", relay=relay_url, error=str(e))
        return relay_url, 0, 0, 0, start_time, False


def _create_filter(since: int, until: int, config: FilterConfig) -> Filter:
    """Build a nostr-sdk Filter from the given time range and filter configuration.

    Supports standard fields (ids, kinds, authors) and tag filters specified
    as ``{tag_letter: [values]}`` (e.g., ``{"e": ["event_id"], "t": ["hashtag"]}``).
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
                    _worker_log(
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
        batch: EventBatch containing nostr-sdk Events.
        relay: Source relay for attribution.
        brotr: Database interface.
        since: Lower timestamp bound (events must be >= this).
        until: Upper timestamp bound (events must be <= this).

    Returns:
        Tuple of (events_inserted, events_invalid, events_skipped).
    """
    if batch.is_empty():
        return 0, 0, 0

    event_relays: list[EventRelay] = []
    invalid_count = 0

    for evt in batch:
        try:
            if not evt.verify():
                _worker_log(
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
                _worker_log(
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
        except Exception as e:
            _worker_log("DEBUG", "event_parse_error", relay=relay.url, error=str(e))

    total_inserted = 0

    if event_relays:
        batch_size = brotr.config.batch.max_batch_size
        for i in range(0, len(event_relays), batch_size):
            inserted = await brotr.insert_events_relays(event_relays[i : i + batch_size])
            total_inserted += inserted

    return total_inserted, invalid_count, 0


@dataclass(frozen=True, slots=True)
class SyncContext:
    """Immutable context shared across all relay sync operations in a cycle."""

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

    Args:
        relay: Relay to sync from.
        start_time: Inclusive start timestamp (since).
        end_time: Inclusive end timestamp (until).
        ctx: Immutable context with filter, network, timeout, database, and key settings.

    Returns:
        Tuple of (events_synced, invalid_events, skipped_events).
    """
    from nostr_sdk import RelayUrl  # noqa: PLC0415 - Worker fresh import after fork

    from utils.transport import create_client  # noqa: PLC0415 - Worker fresh import

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
    except Exception as e:
        _worker_log("WARNING", "sync_relay_error", relay=relay.url, error=str(e))
    finally:
        with contextlib.suppress(Exception):
            await client.shutdown()

    return events_synced, invalid_events, skipped_events


# =============================================================================
# Service
# =============================================================================


class Synchronizer(BaseService[SynchronizerConfig]):
    """Event synchronization service.

    Collects Nostr events from validated relays and stores them in the
    database. Supports single-process and multi-process (aiomultiprocess)
    modes for high-throughput ingestion.

    Workflow:
        1. Fetch relays from the database (plus any configured overrides).
        2. Load per-relay sync cursors from service_data.
        3. Connect to each relay and fetch events since the last sync.
        4. Validate signatures and timestamps, then batch-insert events.
        5. Update per-relay cursors for the next cycle.
    """

    SERVICE_NAME: ClassVar[str] = ServiceName.SYNCHRONIZER
    CONFIG_CLASS: ClassVar[type[SynchronizerConfig]] = SynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: SynchronizerConfig | None = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: SynchronizerConfig
        self._synced_events: int = 0
        self._synced_relays: int = 0
        self._failed_relays: int = 0
        self._invalid_events: int = 0
        self._skipped_events: int = 0

        self._keys: Keys = self._config.keys.keys  # For NIP-42 authentication

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
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
                except Exception as e:
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

        if self._config.concurrency.max_processes > 1:
            await self._run_multiprocess(relays)
        else:
            await self._run_single_process(relays)

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

    async def _run_single_process(self, relays: list[Relay]) -> None:
        """Sync all relays concurrently in a single process."""
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)

        # Pre-fetch all cursors in one query to avoid N+1 pattern
        cursors = await self._fetch_all_cursors()

        # Batch cursor updates to reduce DB round-trips
        cursor_updates: list[tuple[str, str, str, dict[str, Any]]] = []
        cursor_lock = asyncio.Lock()
        cursor_batch_size = self._config.concurrency.cursor_flush_interval

        async def worker(relay: Relay) -> None:
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

                async def _sync_with_timeout() -> tuple[int, int, int]:
                    """Inner coroutine for wait_for timeout."""
                    return await _sync_relay_events(
                        relay=relay, start_time=start, end_time=end_time, ctx=ctx
                    )

                try:
                    events_synced, invalid_events, skipped_events = await asyncio.wait_for(
                        _sync_with_timeout(), timeout=relay_timeout
                    )

                    self._synced_events += events_synced
                    self._invalid_events += invalid_events
                    self._skipped_events += skipped_events
                    self._synced_relays += 1

                    async with cursor_lock:
                        cursor_updates.append(
                            (
                                self.SERVICE_NAME,
                                DataType.CURSOR,
                                relay.url,
                                {"last_synced_at": end_time},
                            )
                        )
                        # Periodic flush for crash resilience
                        if len(cursor_updates) >= cursor_batch_size:
                            await self._brotr.upsert_service_data(cursor_updates.copy())
                            cursor_updates.clear()

                except Exception as e:
                    self._logger.warning(
                        "relay_sync_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=relay.url,
                    )
                    self._failed_relays += 1

        tasks = [worker(relay) for relay in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                relay_url = relays[i].url if i < len(relays) else "unknown"
                self._logger.error(
                    "worker_unexpected_exception",
                    error=str(result),
                    error_type=type(result).__name__,
                    url=relay_url,
                )
                self._failed_relays += 1

        # Flush remaining cursor updates
        if cursor_updates:
            try:
                await self._brotr.upsert_service_data(cursor_updates)
            except Exception as e:
                self._logger.error(
                    "cursor_batch_upsert_failed",
                    error=str(e),
                    count=len(cursor_updates),
                )

    async def _run_multiprocess(self, relays: list[Relay]) -> None:
        """Sync relays across multiple worker processes via aiomultiprocess.

        Each worker maintains its own database connection. Tasks are
        distributed via a queue for automatic load balancing.
        """
        _set_worker_log_level(self._config.worker_log_level)
        tasks = []
        brotr_config_dump = {
            "pool": self._brotr.pool_config.model_dump(exclude={"database": {"password"}}),
            "batch": self._brotr.config.batch.model_dump(),
            "timeouts": self._brotr.config.timeouts.model_dump(),
        }
        service_config_dump = self._config.model_dump()

        # Pre-fetch all cursors in one query to avoid N+1 pattern
        cursors = await self._fetch_all_cursors()

        for relay in relays:
            start_time = self._get_start_time_from_cache(relay, cursors)
            tasks.append((str(relay.url), start_time, service_config_dump, brotr_config_dump))

        async with aiomultiprocess.Pool(
            processes=self._config.concurrency.max_processes,
            childconcurrency=self._config.concurrency.max_parallel,
        ) as pool:
            results = await pool.starmap(sync_relay_task, tasks)

        cursor_updates: list[tuple[str, str, str, dict[str, Any]]] = []

        for url, events, invalid, skipped, new_time, success in results:
            # Track events even on failure (partial sync may have inserted some)
            self._synced_events += events
            self._invalid_events += invalid
            self._skipped_events += skipped

            if success:
                self._synced_relays += 1

                # Save cursor even for 0 events (time window was processed)
                with contextlib.suppress(Exception):
                    relay = Relay(url)
                    cursor_updates.append(
                        (
                            self.SERVICE_NAME,
                            DataType.CURSOR,
                            relay.url,
                            {"last_synced_at": new_time},
                        )
                    )

        if cursor_updates:
            await self._brotr.upsert_service_data(cursor_updates)

    async def _fetch_relays(self) -> list[Relay]:
        """Fetch validated relays from the database for synchronization."""
        relays: list[Relay] = []

        if not self._config.source.from_database:
            return relays

        rows = await get_all_relays(self._brotr)

        for row in rows:
            url_str = row["url"].strip()
            try:
                relay = Relay(url_str, discovered_at=row["discovered_at"])
                relays.append(relay)
            except Exception as e:
                self._logger.debug("invalid_relay_url", url=url_str, error=str(e))

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def _get_start_time(self, relay: Relay) -> int:
        """Get the sync start timestamp for a relay from its stored cursor.

        Falls back to ``time_range.default_start`` if no cursor exists.
        """
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        cursors = await self._brotr.get_service_data(
            service_name=self.SERVICE_NAME,
            data_type=DataType.CURSOR,
            key=relay.url,
        )

        if cursors and len(cursors) > 0:
            cursor_data = cursors[0].get("value", {})
            last_synced_at = cursor_data.get("last_synced_at")
            if last_synced_at is not None:
                result: int = last_synced_at + 1
                return result

        return self._config.time_range.default_start

    async def _fetch_all_cursors(self) -> dict[str, int]:
        """Batch-fetch all relay sync cursors in a single query.

        Returns:
            Dict mapping relay URL to ``last_synced_at`` timestamp.
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
