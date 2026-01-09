"""
Synchronizer Service for BigBrotr.

Synchronizes Nostr events from relays:
- Connect to relays via WebSocket
- Subscribe to event streams (REQ messages)
- Parse and validate incoming events
- Store events in database via Brotr
- Multiprocessing support for high throughput using a dynamic queue

Usage:
    from core import Brotr
    from services import Synchronizer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    sync = Synchronizer.from_yaml("yaml/services/synchronizer.yaml", brotr=brotr)

    async with brotr.pool:
        async with sync:
            await sync.run_forever(interval=900)
"""

from __future__ import annotations

import asyncio
import atexit
import random
import signal
import time
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

from core.base_service import BaseService
from core.brotr import Brotr
from models import Event, EventRelay, Relay
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.proxy import ProxyConfig


# =============================================================================
# Constants
# =============================================================================

# Nostr protocol constants
HEX_STRING_LENGTH = 64
EVENT_KIND_MAX = 65535

# Batch sizes
BATCH_CURSOR = 50


if TYPE_CHECKING:
    import logging
    from collections.abc import Iterator

# Module constant for worker logging (workers can't access class attributes)
_WORKER_SERVICE_NAME = "synchronizer"

# Worker-level logger instance (created once per worker process)
_WORKER_LOGGER: logging.Logger | None = None


def _get_worker_logger() -> logging.Logger:
    """Get or create logger for worker process with proper configuration."""
    global _WORKER_LOGGER
    if _WORKER_LOGGER is None:
        import logging
        import sys

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
            _WORKER_LOGGER.setLevel(logging.DEBUG)
            # Prevent propagation to root logger
            _WORKER_LOGGER.propagate = False

    return _WORKER_LOGGER


def _format_kv(kwargs: dict[str, Any]) -> str:
    """Format kwargs as key=value pairs with proper escaping."""
    if not kwargs:
        return ""
    parts = []
    for k, v in kwargs.items():
        s = str(v)
        # Quote if contains spaces, equals, or quotes
        if " " in s or "=" in s or '"' in s or "'" in s:
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{k}="{escaped}"')
        else:
            parts.append(f"{k}={s}")
    return " " + " ".join(parts)


def _worker_log(level: str, message: str, **kwargs: Any) -> None:
    """
    Log from worker process using Python logging module.

    Configures logging per-process on first call for multiprocess compatibility.
    Format is consistent with the main Logger class.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        **kwargs: Additional key=value pairs to include
    """
    import logging

    logger = _get_worker_logger()
    log_level = getattr(logging, level.upper(), logging.INFO)

    if logger.isEnabledFor(log_level):
        formatted = message + _format_kv(kwargs)
        logger.log(log_level, formatted)


# =============================================================================
# Configuration
# =============================================================================


# =============================================================================
# Utilities
# =============================================================================


class EventBatch:
    """
    Batch container for Nostr events with time bounds.

    Used by Synchronizer to collect events within a time interval
    and track min/max created_at timestamps.

    Attributes:
        since: Minimum timestamp (inclusive) for events in batch
        until: Maximum timestamp (inclusive) for events in batch
        limit: Maximum number of events allowed in batch
        size: Current number of events in batch
        events: List of Event objects in batch
        min_created_at: Lowest created_at timestamp in batch (or None if empty)
        max_created_at: Highest created_at timestamp in batch (or None if empty)
    """

    def __init__(self, since: int, until: int, limit: int) -> None:
        """
        Initialize an EventBatch.

        Args:
            since: Minimum timestamp for events (inclusive)
            until: Maximum timestamp for events (inclusive)
            limit: Maximum number of events to store
        """
        self.since = since
        self.until = until
        self.limit = limit
        self.size = 0
        self.events: list[NostrEvent] = []
        self.min_created_at: int | None = None
        self.max_created_at: int | None = None

    def append(self, event: NostrEvent) -> None:
        """
        Add an event to the batch if within time bounds.

        Args:
            event: NostrEvent to add to batch

        Raises:
            OverflowError: If batch has reached its limit
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
    """Event filter configuration."""

    ids: list[str] | None = Field(default=None, description="Event IDs to sync (None = all)")
    kinds: list[int] | None = Field(default=None, description="Event kinds to sync (None = all)")
    authors: list[str] | None = Field(default=None, description="Authors to sync (None = all)")
    tags: dict[str, list[str]] | None = Field(default=None, description="Tag filters (None = all)")
    limit: int = Field(default=500, ge=1, le=5000, description="Events per request")

    @field_validator("kinds", mode="after")
    @classmethod
    def validate_kinds(cls, v: list[int] | None) -> list[int] | None:
        """Validate event kinds are within valid range (0-65535)."""
        if v is None:
            return v
        for kind in v:
            if not 0 <= kind <= EVENT_KIND_MAX:
                raise ValueError(f"Event kind {kind} out of valid range (0-{EVENT_KIND_MAX})")
        return v

    @field_validator("ids", "authors", mode="after")
    @classmethod
    def validate_hex_strings(cls, v: list[str] | None) -> list[str] | None:
        """Validate hex strings are valid 64-character hex."""
        if v is None:
            return v
        for hex_str in v:
            if len(hex_str) != HEX_STRING_LENGTH:
                raise ValueError(
                    f"Invalid hex string length: {len(hex_str)} (expected {HEX_STRING_LENGTH})"
                )
            try:
                bytes.fromhex(hex_str)
            except ValueError as e:
                raise ValueError(f"Invalid hex string: {hex_str}") from e
        return v


class TimeRangeConfig(BaseModel):
    """Time range configuration for sync."""

    default_start: int = Field(default=0, ge=0, description="Default start timestamp (0 = epoch)")
    use_relay_state: bool = Field(
        default=True, description="Use per-relay state for start timestamp"
    )
    lookback_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Lookback window in seconds (default: 86400 = 24 hours)",
    )


class NetworkTimeoutsConfig(BaseModel):
    """Timeout settings for a specific network type."""

    request: float = Field(default=30.0, ge=5.0, le=120.0, description="WebSocket request timeout")
    relay: float = Field(default=1800.0, ge=60.0, le=14400.0, description="Max time per relay sync")


class TimeoutsConfig(BaseModel):
    """Timeout configuration for sync operations."""

    clearnet: NetworkTimeoutsConfig = Field(default_factory=NetworkTimeoutsConfig)
    tor: NetworkTimeoutsConfig = Field(
        default_factory=lambda: NetworkTimeoutsConfig(request=60.0, relay=3600.0)
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration."""

    max_parallel: int = Field(
        default=10, ge=1, le=100, description="Max concurrent relay connections per process"
    )
    max_processes: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    stagger_delay: tuple[int, int] = Field(
        default=(0, 60), description="Random delay range (min, max) seconds"
    )


class SourceConfig(BaseModel):
    """Configuration for relay source selection."""

    from_database: bool = Field(default=True, description="Fetch relays from database")
    max_metadata_age: int = Field(
        default=43200,
        ge=0,
        description="Only sync relays checked within N seconds",
    )
    require_readable: bool = Field(default=True, description="Only sync readable relays")


class RelayOverrideTimeouts(BaseModel):
    """Override timeouts for a specific relay."""

    request: float | None = None
    relay: float | None = None


class RelayOverride(BaseModel):
    """Override settings for specific relays."""

    url: str
    timeouts: RelayOverrideTimeouts = Field(default_factory=RelayOverrideTimeouts)


class SynchronizerConfig(BaseModel):
    """Synchronizer configuration."""

    interval: float = Field(default=900.0, ge=60.0, description="Seconds between sync cycles")
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    time_range: TimeRangeConfig = Field(default_factory=TimeRangeConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    overrides: list[RelayOverride] = Field(default_factory=list)


# =============================================================================
# Worker Logic (Pure Functions for Multiprocessing)
# =============================================================================

# Global variable for worker process DB connection
_WORKER_BROTR: Brotr | None = None
_WORKER_CLEANUP_REGISTERED: bool = False
_WORKER_BROTR_LOCK: asyncio.Lock | None = None


def _get_worker_lock() -> asyncio.Lock:
    """
    Get or create the asyncio.Lock for worker Brotr initialization.

    The lock is created lazily on first access. This is safe because Lock()
    creation is synchronous and atomic in Python's GIL.
    """
    global _WORKER_BROTR_LOCK
    if _WORKER_BROTR_LOCK is None:
        _WORKER_BROTR_LOCK = asyncio.Lock()
    return _WORKER_BROTR_LOCK


def _reset_worker_state() -> None:
    """
    Reset all worker globals to initial state.

    Used for test isolation to ensure each test starts with clean state.
    This prevents test pollution where one test's state affects another.
    """
    global _WORKER_BROTR, _WORKER_CLEANUP_REGISTERED, _WORKER_BROTR_LOCK
    _WORKER_BROTR = None
    _WORKER_CLEANUP_REGISTERED = False
    _WORKER_BROTR_LOCK = None


def _cleanup_worker_brotr() -> None:
    """
    Cleanup function to close the worker's database connection.

    Called automatically when the worker process terminates via atexit or signal.
    Uses asyncio.run() to properly close the async pool connection.
    """
    global _WORKER_BROTR
    if _WORKER_BROTR is not None:
        try:
            # Create a new event loop for cleanup since the worker's loop may be closed
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_WORKER_BROTR.pool.close())
            finally:
                loop.close()
        except Exception:
            # Best effort cleanup - don't raise during process termination
            pass
        finally:
            _WORKER_BROTR = None


def _signal_handler(signum: int, frame: Any) -> None:
    """Signal handler that ensures cleanup before exit."""
    _cleanup_worker_brotr()
    # Re-raise with default handler for proper exit code
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


async def _get_worker_brotr(brotr_config: dict[str, Any]) -> Brotr:
    """
    Get or initialize the global Brotr instance for the current worker process.

    This function manages a per-process database connection that is reused
    across all tasks executed by the worker. The connection is automatically
    cleaned up when the worker process terminates via atexit handler or signal.

    Uses double-check locking pattern to prevent race conditions when multiple
    async tasks call this function concurrently within the same worker process.
    The pattern: check -> lock -> re-check -> initialize ensures only one
    task performs initialization while others wait.
    """
    global _WORKER_BROTR, _WORKER_CLEANUP_REGISTERED

    # Fast path: return existing connection without lock
    if _WORKER_BROTR is not None:
        return _WORKER_BROTR

    # Slow path: acquire lock and double-check before initializing
    async with _get_worker_lock():
        # Re-check after acquiring lock (another task may have initialized)
        if _WORKER_BROTR is None:
            _WORKER_BROTR = Brotr.from_dict(brotr_config)
            await _WORKER_BROTR.pool.connect()

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
    relay_network: str,
    start_time: int,
    config_dict: dict[str, Any],
    brotr_config: dict[str, Any],
) -> tuple[str, int, int, int, int, bool]:
    """
    Standalone task to sync a single relay.
    Designed to be run in a worker process.

    Returns:
        tuple(relay_url, events_synced, invalid_events, skipped_events, new_end_time, success)
        success is True if sync completed (even with 0 events), False on error/timeout
    """
    try:
        # Reconstruct Relay object (can't pickle Relay across processes)
        relay = Relay(relay_url)

        # Reconstruct config object
        config = SynchronizerConfig(**config_dict)

        # Get keys for NIP-42 auth (already loaded from env by KeysConfig)
        keys: Keys | None = config.keys.keys

        # Determine network config
        net_config = config.timeouts.clearnet
        if relay.network == NetworkType.TOR:
            net_config = config.timeouts.tor

        # Apply override if exists
        relay_timeout = net_config.relay
        request_timeout = net_config.request

        for override in config.overrides:
            if override.url == str(relay.url):
                if override.timeouts.relay is not None:
                    relay_timeout = override.timeouts.relay
                if override.timeouts.request is not None:
                    request_timeout = override.timeouts.request
                break

        # Get DB connection
        brotr = await _get_worker_brotr(brotr_config)

        # Calculate end time (lookback window from now)
        end_time = int(time.time()) - config.time_range.lookback_seconds

        if start_time >= end_time:
            return relay.url, 0, 0, 0, start_time, True  # No work needed, still success

        events_synced = 0
        invalid_events = 0
        skipped_events = 0

        async def _sync_with_client() -> tuple[int, int, int]:
            """Inner coroutine for wait_for timeout."""
            return await _sync_relay_events(
                relay=relay,
                start_time=start_time,
                end_time=end_time,
                filter_config=config.filter,
                proxy_config=config.proxy,
                request_timeout=request_timeout,
                brotr=brotr,
                keys=keys,
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

        except asyncio.TimeoutError:
            _worker_log("WARNING", "sync_timeout", relay=relay.url)
            return relay.url, events_synced, invalid_events, skipped_events, start_time, False
        except Exception as e:
            _worker_log("WARNING", "sync_error", relay=relay.url, error=str(e))
            return relay.url, events_synced, invalid_events, skipped_events, start_time, False

    except Exception as e:
        _worker_log("ERROR", "worker_init_error", relay=relay_url, error=str(e))
        return relay_url, 0, 0, 0, start_time, False


def _create_filter(since: int, until: int, config: FilterConfig) -> Filter:
    """
    Create a Nostr filter from config using nostr-sdk.

    Supports standard filter fields plus tag filters:
    - ids: Event IDs to filter
    - kinds: Event kinds to filter
    - authors: Author public keys to filter
    - tags: Dict of {tag_letter: [values]} for tag filtering
            e.g., {"e": ["event_id_hex"], "p": ["pubkey_hex"], "t": ["hashtag"]}
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

    # Handle tag filters
    # Tags are specified as {"tag_letter": ["value1", "value2"], ...}
    # e.g., {"e": ["event_id"], "p": ["pubkey"], "t": ["hashtag"], "d": ["identifier"]}
    if config.tags:
        for tag_letter, values in config.tags.items():
            if not values:
                continue

            # Convert single letter string to Alphabet enum
            # Tag letters must be single lowercase a-z characters
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
    """
    Insert a batch of events into the database.

    Validates event signatures and timestamps before insertion.

    Args:
        batch: EventBatch containing nostr-sdk Events
        relay: Relay instance for the source relay
        brotr: Database interface
        since: Filter since timestamp (events must be >= this)
        until: Filter until timestamp (events must be <= this)

    Returns:
        tuple[int, int, int]: (events_inserted, events_invalid, events_skipped)
    """
    if batch.is_empty():
        return 0, 0, 0

    event_relays: list[EventRelay] = []
    invalid_count = 0

    for evt in batch:
        try:
            # Validate event signature before processing
            if not evt.verify():
                _worker_log(
                    "WARNING",
                    "invalid_event_signature",
                    relay=relay.url,
                    event_id=evt.id().to_hex(),
                )
                invalid_count += 1
                continue

            # Validate event timestamp is within requested filter range
            # Relays can be buggy or malicious, so we don't trust them blindly
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
    total_skipped = 0

    if event_relays:
        batch_size = brotr.config.batch.max_batch_size
        for i in range(0, len(event_relays), batch_size):
            inserted, skipped = await brotr.insert_events_relays(event_relays[i : i + batch_size])
            total_inserted += inserted
            total_skipped += skipped

    return total_inserted, invalid_count, total_skipped


async def _sync_relay_events(
    relay: Relay,
    start_time: int,
    end_time: int,
    filter_config: FilterConfig,
    proxy_config: ProxyConfig,
    request_timeout: float,
    brotr: Brotr,
    keys: Keys,
) -> tuple[int, int, int]:
    """
    Core sync algorithm for a single relay using nostr-sdk.

    Args:
        relay: Relay instance to sync from
        start_time: Start timestamp (since)
        end_time: End timestamp (until)
        filter_config: Event filter configuration
        proxy_config: Overlay network proxy configuration (Tor, I2P, Loki)
        request_timeout: Request timeout in seconds
        brotr: Database interface
        keys: Nostr keys for NIP-42 authentication

    Returns:
        tuple[int, int, int]: (events_synchronized, invalid_events, skipped_events)
    """
    from nostr_sdk import RelayUrl

    from utils.transport import create_client

    events_synced = 0
    invalid_events = 0
    skipped_events = 0

    # Get proxy URL for overlay networks
    proxy_url = proxy_config.get_proxy_url(relay.network)

    # Create client using transport utility
    client = create_client(keys, proxy_url)
    await client.add_relay(RelayUrl.parse(relay.url))

    try:
        await client.connect()

        # Create filter for time range
        f = _create_filter(start_time, end_time, filter_config)

        # Fetch events
        events = await client.fetch_events(f, timedelta(seconds=request_timeout))
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
                batch, relay, brotr, start_time, end_time
            )

        await client.disconnect()
    except Exception as e:
        _worker_log("WARNING", "sync_relay_error", relay=relay.url, error=str(e))
    finally:
        try:
            await client.shutdown()
        except Exception:
            pass

    return events_synced, invalid_events, skipped_events


# =============================================================================
# Service
# =============================================================================


class Synchronizer(BaseService[SynchronizerConfig]):
    """
    Event synchronization service.

    Synchronizes Nostr events from validated relays:
    - Connects to relays via WebSocket using nostr-sdk
    - Subscribes to event streams with configurable filters
    - Validates event signatures and timestamps
    - Stores events in database via Brotr
    - Supports multicore processing via aiomultiprocess for high throughput

    Workflow:
    1. Fetch relays from database (requires recent Monitor check)
    2. Load per-relay sync cursor from service_data table
    3. Connect to relays and request events since last sync
    4. Validate and insert events into database
    5. Update per-relay cursor for next sync cycle

    Configuration:
        - filter: Event kinds, authors, tags to sync
        - timeouts: Per-network (clearnet/tor) request and relay timeouts
        - concurrency: Parallel connections and worker processes
        - source: Relay selection criteria (metadata age, readability)
        - overrides: Per-relay timeout overrides for high-traffic relays
    """

    SERVICE_NAME: ClassVar[str] = "synchronizer"
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

        # Nostr keys for NIP-42 authentication
        self._keys: Keys | None = self._config.keys.keys

    async def run(self) -> None:
        """Run synchronization cycle."""
        cycle_start = time.time()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0
        self._invalid_events = 0
        self._skipped_events = 0

        # Fetch relays
        relays = await self._fetch_relays()

        # Always add overrides if they are not in the list
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

        elapsed = time.time() - cycle_start
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
        """Run sync in single process using shared sync algorithm."""
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)

        # Collect cursor updates for batch upsert (H8: batch cursor upserts)
        cursor_updates: list[tuple[str, str, str, dict[str, Any]]] = []
        cursor_lock = asyncio.Lock()
        cursor_batch_size = BATCH_CURSOR  # Flush every N successful relays

        # Lock for thread-safe counter increments (H9: prevent race conditions)
        counter_lock = asyncio.Lock()

        async def worker(relay: Relay) -> None:
            async with semaphore:
                # Determine network config
                net_config = self._config.timeouts.clearnet
                if relay.network == NetworkType.TOR:
                    net_config = self._config.timeouts.tor

                # Apply override
                relay_timeout = net_config.relay
                request_timeout = net_config.request

                for override in self._config.overrides:
                    if override.url == str(relay.url):
                        if override.timeouts.relay is not None:
                            relay_timeout = override.timeouts.relay
                        if override.timeouts.request is not None:
                            request_timeout = override.timeouts.request
                        break

                start = await self._get_start_time(relay)
                end_time = int(time.time()) - self._config.time_range.lookback_seconds
                if start >= end_time:
                    return

                async def _sync_with_timeout() -> tuple[int, int, int]:
                    """Inner coroutine for wait_for timeout."""
                    return await _sync_relay_events(
                        relay=relay,
                        start_time=start,
                        end_time=end_time,
                        filter_config=self._config.filter,
                        proxy_config=self._config.proxy,
                        request_timeout=request_timeout,
                        brotr=self._brotr,
                        keys=self._keys,
                    )

                try:
                    events_synced, invalid_events, skipped_events = await asyncio.wait_for(
                        _sync_with_timeout(), timeout=relay_timeout
                    )

                    # Thread-safe counter updates (H9)
                    async with counter_lock:
                        self._synced_events += events_synced
                        self._invalid_events += invalid_events
                        self._skipped_events += skipped_events
                        self._synced_relays += 1

                    # Collect cursor update for batch upsert (H8)
                    async with cursor_lock:
                        cursor_updates.append(
                            (
                                "synchronizer",
                                "cursor",
                                relay.url,
                                {"last_synced_at": end_time},
                            )
                        )
                        # Periodic checkpoint for crash resilience
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
                    async with counter_lock:
                        self._failed_relays += 1

        tasks = [worker(relay) for relay in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any exceptions that escaped the worker's try/except (H7)
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

        # Final batch upsert for remaining cursors (H8)
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
        """Run sync using aiomultiprocess Pool (Queue-based balancing)."""

        # Prepare tasks arguments
        tasks = []
        brotr_config_dump = {
            "pool": self._brotr.pool.config.model_dump(),
            "batch": self._brotr.config.batch.model_dump(),
            "timeouts": self._brotr.config.timeouts.model_dump(),
        }
        service_config_dump = self._config.model_dump()

        # Batch fetch all cursors in one query (avoid N+1 pattern)
        cursors = await self._fetch_all_cursors()

        for relay in relays:
            start_time = self._get_start_time_from_cache(relay, cursors)
            tasks.append(
                (str(relay.url), relay.network, start_time, service_config_dump, brotr_config_dump)
            )

        async with aiomultiprocess.Pool(
            processes=self._config.concurrency.max_processes,
            childconcurrency=self._config.concurrency.max_parallel,
        ) as pool:
            results = await pool.starmap(sync_relay_task, tasks)

        # Process results and collect cursor updates
        cursor_updates: list[tuple[str, str, str, dict[str, Any]]] = []

        for url, events, invalid, skipped, new_time, success in results:
            # Track events regardless of success (partial sync may have inserted some)
            self._synced_events += events
            self._invalid_events += invalid
            self._skipped_events += skipped

            # Only count as synced relay if sync was successful
            if success:
                self._synced_relays += 1

                # Collect cursor update for batch upsert
                # Save cursor even if 0 events - time window was successfully processed
                try:
                    relay = Relay(url)
                    cursor_updates.append(
                        (
                            "synchronizer",
                            "cursor",
                            relay.url,
                            {"last_synced_at": new_time},
                        )
                    )
                except Exception:
                    pass  # Skip invalid URLs

        # Batch upsert all cursors
        if cursor_updates:
            await self._brotr.upsert_service_data(cursor_updates)

    async def _fetch_relays(self) -> list[Relay]:
        """Fetch relays to sync from the relays table."""
        relays: list[Relay] = []

        if not self._config.source.from_database:
            return relays

        # Fetch all validated relays from the relays table
        query = """
            SELECT url, network, discovered_at
            FROM relays
            ORDER BY discovered_at ASC
        """

        rows = await self._brotr.pool.fetch(query)

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
        """
        Get start timestamp for relay sync.

        Reads cursor from service_data, falls back to default if none found.
        """
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        # Read cursor from service_data (O(1) lookup vs O(n) scan on events)
        cursors = await self._brotr.get_service_data(
            service_name="synchronizer",
            data_type="cursor",
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
        """
        Batch fetch all relay cursors in one query.

        Returns dict mapping relay URL to last_synced_at timestamp.
        This avoids N+1 queries when preparing tasks for multiprocess sync.
        """
        if not self._config.time_range.use_relay_state:
            return {}

        records = await self._brotr.pool.fetch(
            """
            SELECT data_key, (data->>'last_synced_at')::BIGINT as cursor
            FROM service_data
            WHERE service_name = 'synchronizer' AND data_type = 'cursor'
            """
        )
        return {r["data_key"]: r["cursor"] for r in records if r["cursor"] is not None}

    def _get_start_time_from_cache(self, relay: Relay, cursors: dict[str, int]) -> int:
        """
        Get start timestamp for relay from pre-fetched cursor cache.

        Args:
            relay: Relay to get start time for
            cursors: Dict of relay URL -> last_synced_at from _fetch_all_cursors

        Returns:
            Start timestamp (cursor + 1 if found, else default_start)
        """
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        cursor = cursors.get(relay.url)
        if cursor is not None:
            return cursor + 1

        return self._config.time_range.default_start
