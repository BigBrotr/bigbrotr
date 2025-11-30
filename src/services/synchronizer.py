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
import random
import time
from typing import Any, Iterator, Optional

import aiomultiprocess
from nostr_tools import Client, Event, Filter, Relay, RelayValidationError
from pydantic import BaseModel, Field

from core.base_service import BaseService
from core.brotr import Brotr


SERVICE_NAME = "synchronizer"


def _worker_log(level: str, message: str, **kwargs: Any) -> None:
    """
    Log from worker process using print() for multiprocess compatibility.

    aiomultiprocess captures stdout from child processes, so print() works
    while logging module doesn't propagate across process boundaries.
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kv = " ".join(f"{k}={v}" for k, v in kwargs.items())
    print(f"{timestamp} {level} {SERVICE_NAME}.worker: {message} {kv}".strip(), flush=True)


# =============================================================================
# Utilities
# =============================================================================


class RawEventBatch:
    """
    Batch container for raw Nostr events with time bounds.

    Used by Synchronizer to collect events within a time interval
    and track min/max created_at timestamps.
    """

    def __init__(self, since: int, until: int, limit: int) -> None:
        self.since = since
        self.until = until
        self.limit = limit
        self.size = 0
        self.raw_events: list[dict[str, Any]] = []
        self.min_created_at: Optional[int] = None
        self.max_created_at: Optional[int] = None

    def append(self, raw_event: dict[str, Any]) -> None:
        """Add an event to the batch if valid."""
        if not isinstance(raw_event, dict):
            return

        created_at = raw_event.get("created_at")
        if not isinstance(created_at, int) or created_at < 0:
            return
        if created_at < self.since or created_at > self.until:
            return

        if self.size >= self.limit:
            raise OverflowError("Batch limit reached")

        self.raw_events.append(raw_event)
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
        return self.size

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.raw_events)


# =============================================================================
# Configuration
# =============================================================================


class TorConfig(BaseModel):
    """Tor proxy configuration."""

    enabled: bool = Field(default=True, description="Enable Tor proxy for .onion relays")
    host: str = Field(default="127.0.0.1", description="Tor proxy host")
    port: int = Field(default=9050, ge=1, le=65535, description="Tor proxy port")


class FilterConfig(BaseModel):
    """Event filter configuration."""

    ids: Optional[list[str]] = Field(default=None, description="Event IDs to sync (None = all)")
    kinds: Optional[list[int]] = Field(default=None, description="Event kinds to sync (None = all)")
    authors: Optional[list[str]] = Field(default=None, description="Authors to sync (None = all)")
    tags: Optional[dict[str, list[str]]] = Field(default=None, description="Tag filters (None = all)")
    limit: int = Field(default=500, ge=1, le=5000, description="Events per request")


class TimeRangeConfig(BaseModel):
    """Time range configuration for sync."""

    default_start: int = Field(
        default=0,
        ge=0,
        description="Default start timestamp (0 = epoch)"
    )
    use_relay_state: bool = Field(
        default=True,
        description="Use per-relay state for start timestamp"
    )
    lookback_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Lookback window in seconds (default: 86400 = 24 hours)"
    )


class NetworkTimeoutsConfig(BaseModel):
    """Timeout settings for a specific network type."""

    request: float = Field(
        default=30.0, ge=5.0, le=120.0, description="WebSocket request timeout"
    )
    relay: float = Field(
        default=1800.0, ge=60.0, le=14400.0, description="Max time per relay sync"
    )


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
    max_processes: int = Field(
        default=1, ge=1, le=32, description="Number of worker processes"
    )
    stagger_delay: tuple[int, int] = Field(
        default=(0, 60), description="Random delay range (min, max) seconds"
    )


class SourceConfig(BaseModel):
    """Configuration for relay source selection."""

    from_database: bool = Field(default=True, description="Fetch relays from database")
    max_metadata_age: int = Field(
        default=43200,  # 12 hours
        ge=0,
        description="Only sync relays checked within N seconds"
    )
    require_readable: bool = Field(default=True, description="Only sync readable relays")


class RelayOverrideTimeouts(BaseModel):
    """Override timeouts for a specific relay."""
    request: Optional[float] = None
    relay: Optional[float] = None


class RelayOverride(BaseModel):
    """Override settings for specific relays."""
    url: str
    timeouts: RelayOverrideTimeouts = Field(default_factory=RelayOverrideTimeouts)


class SynchronizerConfig(BaseModel):
    """Synchronizer configuration."""

    interval: float = Field(
        default=900.0, ge=60.0, description="Seconds between sync cycles"
    )
    tor: TorConfig = Field(default_factory=TorConfig)
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
_WORKER_BROTR: Optional[Brotr] = None
_WORKER_CLEANUP_REGISTERED: bool = False


def _cleanup_worker_brotr() -> None:
    """
    Cleanup function to close the worker's database connection.

    Called automatically when the worker process terminates via atexit.
    Uses asyncio.run() to properly close the async pool connection.
    """
    global _WORKER_BROTR
    if _WORKER_BROTR is not None:
        try:
            # Create a new event loop for cleanup since the worker's loop may be closed
            import asyncio
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


async def _get_worker_brotr(brotr_config: dict[str, Any]) -> Brotr:
    """
    Get or initialize the global Brotr instance for the current worker process.

    This function manages a per-process database connection that is reused
    across all tasks executed by the worker. The connection is automatically
    cleaned up when the worker process terminates via atexit handler.
    """
    global _WORKER_BROTR, _WORKER_CLEANUP_REGISTERED

    if _WORKER_BROTR is None:
        _WORKER_BROTR = Brotr.from_dict(brotr_config)
        await _WORKER_BROTR.pool.connect()

        # Register cleanup handler only once per worker process
        if not _WORKER_CLEANUP_REGISTERED:
            import atexit
            atexit.register(_cleanup_worker_brotr)
            _WORKER_CLEANUP_REGISTERED = True

    return _WORKER_BROTR


async def sync_relay_task(
    relay_url: str,
    relay_network: str,
    start_time: int,
    config_dict: dict[str, Any],
    brotr_config: dict[str, Any]
) -> tuple[str, int, int]:
    """
    Standalone task to sync a single relay.
    Designed to be run in a worker process.

    Returns:
        tuple(relay_url, events_synced, new_end_time)
    """
    try:
        # Reconstruct config object
        config = SynchronizerConfig(**config_dict)

        # Determine network config
        net_config = config.timeouts.clearnet
        if relay_network == "tor":
            net_config = config.timeouts.tor

        # Apply override if exists
        relay_timeout = net_config.relay
        request_timeout = net_config.request

        for override in config.overrides:
            if override.url == relay_url:
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
            return relay_url, 0, start_time

        # Create client with optional SOCKS5 proxy for Tor
        socks5_proxy = None
        if relay_network == "tor" and config.tor.enabled:
            socks5_proxy = f"socks5://{config.tor.host}:{config.tor.port}"

        events_synced = 0
        try:
            async with asyncio.timeout(relay_timeout):
                client = Client(
                    relay=Relay(relay_url),
                    timeout=int(request_timeout),
                    socks5_proxy_url=socks5_proxy,
                )

                async with client:
                    # Use shared sync algorithm
                    events_synced = await _sync_relay_events(
                        client=client,
                        relay_url=relay_url,
                        relay_network=relay_network,
                        start_time=start_time,
                        end_time=end_time,
                        filter_config=config.filter,
                        brotr=brotr
                    )

            if events_synced > 0:
                _worker_log("INFO", "sync_ok", relay=relay_url, events=events_synced)
            return relay_url, events_synced, end_time

        except asyncio.TimeoutError:
            _worker_log("WARNING", "sync_timeout", relay=relay_url)
            return relay_url, events_synced, start_time
        except Exception as e:
            _worker_log("WARNING", "sync_error", relay=relay_url, error=str(e))
            return relay_url, events_synced, start_time

    except Exception as e:
        _worker_log("ERROR", "worker_init_error", relay=relay_url, error=str(e))
        return relay_url, 0, start_time


def _create_filter(since: int, until: int, config: FilterConfig) -> Filter:
    """Create a Nostr filter from config."""
    filter_obj = Filter(since=since, until=until, limit=config.limit)
    if config.ids:
        filter_obj.ids = config.ids
    if config.kinds:
        filter_obj.kinds = config.kinds
    if config.authors:
        filter_obj.authors = config.authors
    if config.tags:
        for k, v in config.tags.items():
            setattr(filter_obj, f"#{k}", v)
    return filter_obj


async def _fetch_batch(client: Client, filter_obj: Filter) -> RawEventBatch:
    """Fetch a batch of events from a relay."""
    batch = RawEventBatch(filter_obj.since, filter_obj.until, filter_obj.limit)
    try:
        sub_id = await client.subscribe(filter_obj)
        async for msg in client.listen_events(sub_id):
            if batch.is_full():
                break
            if len(msg) >= 3 and isinstance(msg[2], dict):
                try:
                    batch.append(msg[2])
                except OverflowError:
                    break
        await client.unsubscribe(sub_id)
    except Exception as e:
        _worker_log("DEBUG", "fetch_batch_error", error=str(e))
    return batch


async def _insert_batch(
    batch: RawEventBatch,
    relay_url: str,
    relay_network: str,
    brotr: Brotr
) -> int:
    """Insert a batch of events into the database."""
    if batch.is_empty():
        return 0

    now = int(time.time())
    events = []
    for raw in batch:
        try:
            evt = Event.from_dict(raw)
            events.append({
                "event_id": evt.id,
                "pubkey": evt.pubkey,
                "created_at": evt.created_at,
                "kind": evt.kind,
                "tags": evt.tags,
                "content": evt.content,
                "sig": evt.sig,
                "relay_url": relay_url,
                "relay_network": relay_network,
                "relay_inserted_at": now,
                "seen_at": now
            })
        except Exception as e:
            _worker_log("DEBUG", "event_parse_error", relay=relay_url, error=str(e))

    if events:
        batch_size = brotr.config.batch.max_batch_size
        for i in range(0, len(events), batch_size):
            await brotr.insert_events(events[i:i + batch_size])

    return len(events)


async def _sync_relay_events(
    client: Client,
    relay_url: str,
    relay_network: str,
    start_time: int,
    end_time: int,
    filter_config: FilterConfig,
    brotr: Brotr
) -> int:
    """
    Core sync algorithm for a single relay.

    This is the shared implementation used by both single-process and
    multiprocess modes. It uses a time-window stack approach to handle
    relays with gaps and large event volumes.

    Args:
        client: Connected nostr_tools Client
        relay_url: Relay URL for attribution
        relay_network: Network type (clearnet/tor)
        start_time: Start timestamp (since)
        end_time: End timestamp (until)
        filter_config: Event filter configuration
        brotr: Database interface

    Returns:
        Number of events synchronized
    """
    events_synced = 0
    until_stack = [end_time]
    current_since = start_time

    while until_stack:
        current_until = until_stack[0]
        f = _create_filter(current_since, current_until, filter_config)
        b = await _fetch_batch(client, f)

        if b.is_empty():
            # No events in this window, move forward
            until_stack.pop(0)
            current_since = current_until + 1
        elif current_since == current_until:
            # Single timestamp window, insert all
            n = await _insert_batch(b, relay_url, relay_network, brotr)
            events_synced += n
            until_stack.pop(0)
            current_since = current_until + 1
        else:
            # Check if we need to split the window
            f.until = b.min_created_at
            b2 = await _fetch_batch(client, f)

            if b2.is_empty():
                # Inconsistent relay response
                break
            if b.min_created_at != b2.max_created_at:
                # Inconsistent relay response
                break

            if b2.min_created_at != b.min_created_at:
                # More events exist earlier, split the window
                mid = (current_until - current_since) // 2 + current_since
                until_stack.insert(0, mid)
            else:
                # Check for more events before min_created_at
                f.until = b.min_created_at - 1
                f.limit = 1
                b3 = await _fetch_batch(client, f)

                if b3.is_empty():
                    # Combine and insert events
                    temp = RawEventBatch(current_since, current_until, 9999)
                    for e in b:
                        if e.get("created_at") != b.min_created_at:
                            temp.append(e)
                    for e in b2:
                        temp.append(e)
                    n = await _insert_batch(temp, relay_url, relay_network, brotr)
                    events_synced += n
                    until_stack.pop(0)
                    current_since = current_until + 1
                else:
                    # More events exist, split further
                    mid = (f.until - current_since) // 2 + current_since
                    until_stack.insert(0, mid)

    return events_synced


# =============================================================================
# Service
# =============================================================================


class Synchronizer(BaseService):
    """
    Event synchronization service.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = SynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[SynchronizerConfig] = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config or SynchronizerConfig())
        self._config: SynchronizerConfig
        self._synced_events: int = 0
        self._synced_relays: int = 0
        self._failed_relays: int = 0

    async def run(self) -> None:
        """Run synchronization cycle."""
        cycle_start = time.time()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0

        # Fetch relays
        relays = await self._fetch_relays()
        
        # Always add overrides if they are not in the list?
        # Or just let _fetch_relays handle it?
        # Let's merge overrides into the relay list if not present.
        known_urls = {r.url for r in relays}
        for override in self._config.overrides:
            if override.url not in known_urls:
                try:
                    # Add override relay, assuming clearnet if not specified or auto-detect
                    # Relay constructor handles parsing
                    r = Relay(override.url)
                    relays.append(r)
                    known_urls.add(r.url)
                except Exception as e:
                    self._logger.warning("invalid_override_relay", url=override.url, error=str(e))

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
            duration=round(elapsed, 2),
        )

    async def _run_single_process(self, relays: list[Relay]) -> None:
        """Run sync in single process using shared sync algorithm."""
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)

        async def worker(relay: Relay) -> None:
            async with semaphore:
                # Determine network config
                net_config = self._config.timeouts.clearnet
                if relay.network == "tor":
                    net_config = self._config.timeouts.tor

                # Apply override
                relay_timeout = net_config.relay
                request_timeout = net_config.request

                for override in self._config.overrides:
                    if override.url == relay.url:
                        if override.timeouts.relay is not None:
                            relay_timeout = override.timeouts.relay
                        if override.timeouts.request is not None:
                            request_timeout = override.timeouts.request
                        break

                start = await self._get_start_time(relay)
                end_time = int(time.time()) - self._config.time_range.lookback_seconds
                if start >= end_time:
                    return

                # Configure SOCKS proxy for Tor
                socks = None
                if relay.network == "tor" and self._config.tor.enabled:
                    socks = f"socks5://{self._config.tor.host}:{self._config.tor.port}"

                try:
                    client = Client(relay, timeout=int(request_timeout), socks5_proxy_url=socks)

                    async with asyncio.timeout(relay_timeout):
                        async with client:
                            # Use shared sync algorithm
                            events_synced = await _sync_relay_events(
                                client=client,
                                relay_url=relay.url,
                                relay_network=relay.network,
                                start_time=start,
                                end_time=end_time,
                                filter_config=self._config.filter,
                                brotr=self._brotr
                            )

                    self._state.setdefault("relay_timestamps", {})[relay.url] = end_time
                    self._synced_events += events_synced
                    self._synced_relays += 1
                except Exception as e:
                    self._logger.warning("relay_sync_failed", url=relay.url, error=str(e))
                    self._failed_relays += 1

        tasks = [worker(r) for r in relays]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_multiprocess(self, relays: list[Relay]) -> None:
        """Run sync using aiomultiprocess Pool (Queue-based balancing)."""
        
        # Prepare tasks arguments
        tasks = []
        brotr_config_dump = {
            "pool": self._brotr.pool.config.model_dump(),
            # Add other brotr settings
            "batch": self._brotr.config.batch.model_dump(),
            "timeouts": self._brotr.config.timeouts.model_dump()
        }
        service_config_dump = self._config.model_dump()
        
        for relay in relays:
            start_time = await self._get_start_time(relay)
            tasks.append((
                relay.url,
                relay.network,
                start_time,
                service_config_dump,
                brotr_config_dump
            ))
            
        async with aiomultiprocess.Pool(
            processes=self._config.concurrency.max_processes,
            childconcurrency=self._config.concurrency.max_parallel
        ) as pool:
            results = await pool.starmap(sync_relay_task, tasks)
            
        # Process results
        for url, events, new_time in results:
            if events > 0 or new_time > 0:
                self._state.setdefault("relay_timestamps", {})[url] = new_time
                self._synced_events += events
                if events > 0:
                    self._synced_relays += 1
            else:
                self._failed_relays += 1

    async def _fetch_relays(self) -> list[Relay]:
        """Fetch relays to sync from database using the latest metadata view."""
        relays: list[Relay] = []

        if not self._config.source.from_database:
            return relays

        threshold = int(time.time()) - self._config.source.max_metadata_age

        # Use the dedicated view for efficient latest metadata retrieval
        query = """
            SELECT relay_url
            FROM relay_metadata_latest
            WHERE generated_at > $1
        """

        if self._config.source.require_readable:
            query += " AND nip66_readable = TRUE"

        rows = await self._brotr.pool.fetch(query, threshold)

        for row in rows:
            relay_url = row["relay_url"].strip()
            try:
                relays.append(Relay(relay_url))
            except RelayValidationError:
                self._logger.debug("invalid_relay_url", url=relay_url)
            except Exception as e:
                self._logger.debug("relay_parse_error", url=relay_url, error=str(e))

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def _get_start_time(self, relay: Relay) -> int:
        """
        Get start timestamp for relay sync.

        Checks persisted state first, then database, then uses default.
        """
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        # Check persisted state first
        relay_timestamps = self._state.get("relay_timestamps", {})
        if relay.url in relay_timestamps:
            return relay_timestamps[relay.url] + 1

        # Check database for latest seen_at
        row = await self._brotr.pool.fetchrow(
            """
            SELECT MAX(er.seen_at) as max_seen
            FROM events_relays er
            WHERE er.relay_url = $1
            """,
            relay.url,
        )

        if row and row["max_seen"] is not None:
            # Get created_at of the event at max_seen
            event_row = await self._brotr.pool.fetchrow(
                """
                SELECT e.created_at
                FROM events e
                JOIN events_relays er ON e.id = er.event_id
                WHERE er.relay_url = $1 AND er.seen_at = $2
                LIMIT 1
                """,
                relay.url,
                row["max_seen"],
            )
            if event_row:
                return event_row["created_at"] + 1

        return self._config.time_range.default_start
