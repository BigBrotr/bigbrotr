"""
Synchronizer Service for BigBrotr.

Synchronizes Nostr events from relays:
- Connect to relays via WebSocket
- Subscribe to event streams (REQ messages)
- Parse and validate incoming events
- Store events in database via Brotr

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

from nostr_tools import Client, Event, Filter, Relay, RelayValidationError
from pydantic import BaseModel, Field

from core.base_service import BaseService
from core.brotr import Brotr


SERVICE_NAME = "synchronizer"


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


class TimeoutsConfig(BaseModel):
    """Timeout configuration for sync operations."""

    request: float = Field(
        default=30.0, ge=5.0, le=120.0, description="WebSocket request timeout"
    )
    relay: float = Field(
        default=1800.0, ge=60.0, le=7200.0, description="Max time per relay sync"
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration."""

    max_parallel: int = Field(
        default=10, ge=1, le=100, description="Max concurrent relay connections"
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


# =============================================================================
# Service
# =============================================================================


class Synchronizer(BaseService):
    """
    Event synchronization service.

    Connects to Nostr relays and syncs events to the database.
    Uses an adaptive time-interval algorithm to handle relays
    with varying amounts of events.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = SynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[SynchronizerConfig] = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        super().__init__(brotr=brotr, config=config or SynchronizerConfig())
        self._config: SynchronizerConfig
        self._synced_events: int = 0
        self._synced_relays: int = 0
        self._failed_relays: int = 0

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Run single synchronization cycle.

        Fetches relays and syncs events from each.
        Call via run_forever() for continuous operation.
        """
        cycle_start = time.time()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0

        # Fetch relays to sync
        relays = await self._fetch_relays()
        if not relays:
            self._logger.info("no_relays_to_sync")
            return

        self._logger.info("sync_started", relay_count=len(relays))

        # Shuffle to avoid always hitting same relays first
        random.shuffle(relays)

        # Process relays with concurrency limit
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)

        async def sync_with_limit(relay: Relay) -> None:
            async with semaphore:
                await self._sync_relay(relay)

        tasks = [sync_with_limit(relay) for relay in relays]
        await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - cycle_start
        self._logger.info(
            "cycle_completed",
            synced_relays=self._synced_relays,
            failed_relays=self._failed_relays,
            synced_events=self._synced_events,
            duration=round(elapsed, 2),
        )

    # -------------------------------------------------------------------------
    # Relay Fetching
    # -------------------------------------------------------------------------

    async def _fetch_relays(self) -> list[Relay]:
        """Fetch relays to sync from database."""
        relays: list[Relay] = []

        if not self._config.source.from_database:
            return relays

        threshold = int(time.time()) - self._config.source.max_metadata_age

        # Query for relays with recent metadata that are readable
        query = """
            SELECT DISTINCT rm.relay_url
            FROM relay_metadata rm
            WHERE rm.generated_at = (
                SELECT MAX(generated_at)
                FROM relay_metadata
                WHERE relay_url = rm.relay_url
            )
            AND rm.generated_at > $1
        """

        if self._config.source.require_readable:
            query += " AND rm.readable = TRUE"

        rows = await self._brotr.pool.fetch(query, threshold)

        for row in rows:
            relay_url = row["relay_url"].strip()
            try:
                relay = Relay(relay_url)
                relays.append(relay)
            except RelayValidationError:
                self._logger.debug("invalid_relay_url", url=relay_url)

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    # -------------------------------------------------------------------------
    # Event Synchronization
    # -------------------------------------------------------------------------

    async def _sync_relay(self, relay: Relay) -> None:
        """
        Sync events from a single relay.

        Uses adaptive time-interval splitting to handle varying event densities.
        """
        # Random stagger to avoid thundering herd
        min_delay, max_delay = self._config.concurrency.stagger_delay
        if max_delay > min_delay:
            await asyncio.sleep(random.randint(min_delay, max_delay))

        # Determine time range
        end_time = int(time.time()) - 86400  # 24 hours ago
        start_time = await self._get_start_time(relay)

        if start_time >= end_time:
            self._logger.debug("relay_up_to_date", relay=relay.url)
            return

        # Create client with optional SOCKS5 proxy for Tor
        socks5_proxy = None
        if relay.network == "tor" and self._config.tor.enabled:
            socks5_proxy = f"socks5://{self._config.tor.host}:{self._config.tor.port}"

        try:
            async with asyncio.timeout(self._config.timeouts.relay):
                events_synced = await self._process_relay_interval(
                    relay, start_time, end_time, socks5_proxy
                )

            if events_synced > 0:
                # Update state with latest sync timestamp
                relay_state = self._state.get("relay_timestamps", {})
                relay_state[relay.url] = end_time
                self._state["relay_timestamps"] = relay_state

            self._synced_relays += 1
            self._synced_events += events_synced
            self._logger.info("relay_synced", relay=relay.url, events=events_synced)

        except asyncio.TimeoutError:
            self._failed_relays += 1
            self._logger.warning("relay_timeout", relay=relay.url)
        except Exception as e:
            self._failed_relays += 1
            self._logger.warning("relay_sync_failed", relay=relay.url, error=str(e))

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

    async def _process_relay_interval(
        self,
        relay: Relay,
        since: int,
        until: int,
        socks5_proxy: Optional[str] = None,
    ) -> int:
        """
        Process events from relay within a time interval.

        Uses adaptive splitting when batches are full.

        Args:
            relay: Relay to sync from
            since: Start timestamp (inclusive)
            until: End timestamp (inclusive)
            socks5_proxy: Optional SOCKS5 proxy URL for Tor relays

        Returns:
            Number of events synced
        """
        total_events = 0

        # Create client using nostr_tools API
        client = Client(
            relay=relay,
            timeout=int(self._config.timeouts.request),
            socks5_proxy_url=socks5_proxy,
        )

        async with client:
            # Stack-based interval processing
            until_stack = [until]
            current_since = since

            while until_stack and self._is_running:
                current_until = until_stack[0]
                filter_obj = self._create_filter(current_since, current_until)

                first_batch = await self._fetch_batch(client, filter_obj)

                if first_batch.is_empty():
                    # No events in interval - move to next
                    until_stack.pop(0)
                    current_since = current_until + 1

                elif current_since == current_until:
                    # Single timestamp interval with events
                    events_inserted = await self._insert_batch(
                        first_batch, relay
                    )
                    total_events += events_inserted
                    until_stack.pop(0)
                    current_since = current_until + 1

                else:
                    # Multi-timestamp interval - check if we got all events
                    filter_obj.until = first_batch.min_created_at
                    second_batch = await self._fetch_batch(client, filter_obj)

                    if second_batch.is_empty():
                        # Unexpected - relay may have inconsistent results
                        self._logger.debug(
                            "unexpected_empty_batch",
                            relay=relay.url,
                            since=current_since,
                            until=first_batch.min_created_at,
                        )
                        break

                    if first_batch.min_created_at != second_batch.max_created_at:
                        # Inconsistent relay behavior
                        self._logger.debug(
                            "inconsistent_relay",
                            relay=relay.url,
                        )
                        break

                    if second_batch.min_created_at != first_batch.min_created_at:
                        # More events exist in earlier time range - split interval
                        mid = (current_until - current_since) // 2 + current_since
                        until_stack.insert(0, mid)
                    else:
                        # All events at min_created_at fetched - check for more
                        filter_obj.until = first_batch.min_created_at - 1
                        filter_obj.limit = 1
                        third_batch = await self._fetch_batch(client, filter_obj)

                        if third_batch.is_empty():
                            # All events fetched for this interval
                            combined_events = [
                                e for e in first_batch
                                if e.get("created_at") != first_batch.min_created_at
                            ]
                            combined_events.extend(second_batch.raw_events)

                            if combined_events:
                                # Create a temporary batch for insertion
                                temp_batch = RawEventBatch(
                                    current_since, current_until, len(combined_events) + 1
                                )
                                for e in combined_events:
                                    temp_batch.append(e)
                                events_inserted = await self._insert_batch(
                                    temp_batch, relay
                                )
                                total_events += events_inserted

                            until_stack.pop(0)
                            current_since = current_until + 1
                        else:
                            # More events exist - split interval
                            mid = (filter_obj.until - current_since) // 2 + current_since
                            until_stack.insert(0, mid)

        return total_events

    def _create_filter(self, since: int, until: int) -> Filter:
        """Create filter for event subscription."""
        filter_obj = Filter(
            since=since,
            until=until,
            limit=self._config.filter.limit,
        )

        if self._config.filter.ids:
            filter_obj.ids = self._config.filter.ids
        if self._config.filter.kinds:
            filter_obj.kinds = self._config.filter.kinds
        if self._config.filter.authors:
            filter_obj.authors = self._config.filter.authors
        if self._config.filter.tags:
            for tag_key, tag_values in self._config.filter.tags.items():
                setattr(filter_obj, f"#{tag_key}", tag_values)

        return filter_obj

    async def _fetch_batch(self, client: Client, filter_obj: Filter) -> RawEventBatch:
        """Fetch a batch of events from relay."""
        batch = RawEventBatch(filter_obj.since, filter_obj.until, filter_obj.limit)

        try:
            subscription_id = await client.subscribe(filter_obj)

            async for message in client.listen_events(subscription_id):
                if batch.is_full():
                    break
                if len(message) >= 3 and isinstance(message[2], dict):
                    try:
                        batch.append(message[2])
                    except OverflowError:
                        break

            await client.unsubscribe(subscription_id)

        except Exception as e:
            self._logger.debug("batch_fetch_error", error=str(e))

        return batch

    async def _insert_batch(self, batch: RawEventBatch, relay: Relay) -> int:
        """
        Insert batch of events into database.

        Returns number of events successfully inserted.
        """
        if batch.is_empty():
            return 0

        seen_at = int(time.time())
        relay_inserted_at = int(time.time())
        events_to_insert: list[dict[str, Any]] = []

        for raw_event in batch:
            try:
                event = Event.from_dict(raw_event)
                events_to_insert.append({
                    "event_id": event.id,
                    "pubkey": event.pubkey,
                    "created_at": event.created_at,
                    "kind": event.kind,
                    "tags": event.tags,
                    "content": event.content,
                    "sig": event.sig,
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "relay_inserted_at": relay_inserted_at,
                    "seen_at": seen_at,
                })
            except Exception as e:
                self._logger.debug("invalid_event", error=str(e))

        if events_to_insert:
            # Insert in batches respecting Brotr batch size
            batch_size = self._brotr.config.batch.max_batch_size
            for i in range(0, len(events_to_insert), batch_size):
                await self._brotr.insert_events(events_to_insert[i : i + batch_size])

        return len(events_to_insert)
