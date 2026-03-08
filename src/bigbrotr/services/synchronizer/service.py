"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Uses ``asyncio.TaskGroup`` with per-network semaphores for structured, bounded concurrency.

The synchronization workflow proceeds as follows:

1. Fetch relays from the database via
   [fetch_relays][bigbrotr.services.synchronizer.queries.fetch_relays]
   (optionally filtered by metadata age).
2. Load per-relay sync cursors from ``service_state`` via
   [Brotr.get_service_state][bigbrotr.core.brotr.Brotr.get_service_state].
3. Connect to each relay and stream events since the last sync timestamp.
4. Insert pre-validated events (filtering, signature verification, and
   deduplication are handled at the fetch layer by ``_fetch_validated``).
5. Update per-relay cursors for the next cycle.

Note:
    Cursor-based pagination ensures each relay is synced incrementally.
    The cursor (``timestamp``) is stored as a
    [ServiceState][bigbrotr.models.service_state.ServiceState] record
    with ``state_type='cursor'``.  Cursor updates are batched (flushed
    every ``flush_interval`` relays) for crash resilience.

    Relay processing order is randomized (shuffled) to avoid
    thundering-herd effects when multiple synchronizer instances run
    concurrently.

See Also:
    [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
        Configuration model for networks, filters, time ranges,
        and concurrency.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for event
        insertion and cursor management.
    [Monitor][bigbrotr.services.monitor.Monitor]: Upstream service that
        health-checks the relays synced here.
    [Finder][bigbrotr.services.finder.Finder]: Downstream consumer that
        discovers relay URLs from the events collected here.
    [connect_relay][bigbrotr.utils.protocol.connect_relay]: High-level
        relay connection helper with automatic SSL fallback.

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
import random
import time
from typing import TYPE_CHECKING, ClassVar

import asyncpg
from nostr_sdk import NostrSdkError

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import ConcurrentStreamMixin, NetworkSemaphoresMixin
from bigbrotr.services.common.queries import upsert_service_states
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.utils.protocol import connect_relay
from bigbrotr.utils.streaming import stream_events

from .configs import SynchronizerConfig
from .queries import delete_stale_cursors, fetch_relays
from .utils import insert_events


_CURSOR_SENTINEL_ID = b"\xff" * 32

if TYPE_CHECKING:
    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Event, Relay


class Synchronizer(
    ConcurrentStreamMixin,
    NetworkSemaphoresMixin,
    BaseService[SynchronizerConfig],
):
    """Event synchronization service.

    Collects Nostr events from validated relays and stores them in the
    database. Uses ``asyncio.TaskGroup`` with per-network semaphores for
    structured, bounded concurrency.

    Each cycle fetches relays from the database, loads per-relay sync
    cursors from ``service_state``, connects to each relay to stream events
    since the last sync, batch-inserts pre-validated events, and updates
    per-relay cursors for the next cycle.

    Note:
        The relay list is shuffled before processing to prevent all
        synchronizer instances from hitting the same relays in the same
        order, reducing thundering-herd effects.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Configuration model for this service.
        [Monitor][bigbrotr.services.monitor.Monitor]: Upstream service
            that health-checks relays before they are synced.
        [Finder][bigbrotr.services.finder.Finder]: Downstream consumer
            that discovers relay URLs from the events collected here.
        [Brotr.get_service_state][bigbrotr.core.brotr.Brotr.get_service_state]:
            Fetches per-relay cursor values.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.SYNCHRONIZER
    CONFIG_CLASS: ClassVar[type[SynchronizerConfig]] = SynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: SynchronizerConfig | None = None,
    ) -> None:
        config = config or SynchronizerConfig()
        super().__init__(brotr=brotr, config=config, networks=config.networks)
        self._config: SynchronizerConfig
        self._keys: Keys = self._config.keys.keys  # For NIP-42 authentication

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
        await self.synchronize()

    async def cleanup(self) -> int:
        """Remove stale cursor state for relays that no longer exist."""
        return await delete_stale_cursors(self._brotr)

    async def synchronize(self) -> int:
        """Fetch relays and sync events from all of them.

        Returns:
            Total events synced across all relays.
        """
        relays = await self.fetch_relays()

        self.set_gauge("relays_scanned", 0)
        self.set_gauge("events_synced", 0)

        if not relays:
            self._logger.info("no_relays_to_sync")
            return 0

        self._logger.info("sync_started", relay_count=len(relays))
        random.shuffle(relays)

        cursors = await self.fetch_cursors()
        return await self._run_sync(relays, cursors)

    # ── Relay fetching ────────────────────────────────────────────

    async def fetch_relays(self) -> list[Relay]:
        """Fetch validated relays from the database for synchronization.

        Filters relays to only include enabled networks, avoiding unnecessary
        relay loading for disabled network types.

        Returns:
            List of relays to sync (filtered by enabled networks).
        """
        all_relays = await fetch_relays(self._brotr)
        enabled = set(self._config.networks.get_enabled_networks())
        relays = [r for r in all_relays if r.network in enabled]

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def fetch_cursors(self) -> dict[str, SyncCursor]:
        """Batch-fetch all relay sync cursors in a single query.

        Returns:
            Dict mapping relay URL to SyncCursor.
        """
        states = await self._brotr.get_service_state(self.SERVICE_NAME, ServiceStateType.CURSOR)
        cursors: dict[str, SyncCursor] = {}
        for s in states:
            if "timestamp" not in s.state_value:
                continue
            try:
                ts = int(s.state_value["timestamp"])
                id_hex = s.state_value.get("id")
                event_id = bytes.fromhex(str(id_hex)) if id_hex is not None else _CURSOR_SENTINEL_ID
                cursors[s.state_key] = SyncCursor(key=s.state_key, timestamp=ts, id=event_id)
            except (ValueError, TypeError) as e:
                self._logger.warning("invalid_cursor_data", relay=s.state_key, error=str(e))
        return cursors

    # ── Sync orchestration ────────────────────────────────────────

    async def _run_sync(
        self,
        relays: list[Relay],
        cursors: dict[str, SyncCursor],
    ) -> int:
        """Sync all relays concurrently and aggregate results.

        Uses ``_iter_concurrent()`` with per-network semaphores to bound
        simultaneous WebSocket connections. Results stream per-relay,
        enabling progressive metric updates as each relay completes.

        Cursor updates are batched and flushed every
        ``flush_interval`` relays for crash resilience.

        Returns:
            Total events synced.
        """
        cursor_updates: list[ServiceState] = []
        cursor_lock = asyncio.Lock()
        phase_start = time.monotonic()

        total_events = 0
        relays_scanned = 0
        scan_failures = 0

        async def _worker(relay: Relay) -> int | None:
            nonlocal scan_failures
            try:
                return await self._sync_single_relay(
                    relay, cursors, cursor_updates, cursor_lock, phase_start
                )
            except Exception as e:  # Worker exception boundary — protects TaskGroup
                self._logger.error(
                    "sync_worker_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    relay=relay.url,
                )
                scan_failures += 1
                return None

        async for events in self._iter_concurrent(relays, _worker):
            total_events += events
            relays_scanned += 1
            self.set_gauge("relays_scanned", relays_scanned)
            self.set_gauge("events_synced", total_events)

        await self._flush_cursors(cursor_updates)

        self.set_gauge("relays_scanned", relays_scanned)
        self.set_gauge("events_synced", total_events)
        self.inc_counter("total_events_synced", total_events)
        self.inc_counter("total_sync_failures", scan_failures)

        self._logger.info(
            "sync_completed",
            events_synced=total_events,
            relays_scanned=relays_scanned,
            scan_failures=scan_failures,
        )
        return total_events

    async def _sync_single_relay(
        self,
        relay: Relay,
        cursors: dict[str, SyncCursor],
        cursor_updates: list[ServiceState],
        cursor_lock: asyncio.Lock,
        phase_start: float,
    ) -> int | None:
        """Sync events from a single relay with semaphore-bounded concurrency.

        Creates a WebSocket client, connects to the relay, and consumes the
        [stream_events][bigbrotr.services.synchronizer.utils.stream_events]
        generator to fetch and insert events in ascending time order.

        The cursor is updated to ``end_time`` on normal completion. On
        partial completion (error), the cursor is set to the ``created_at``
        of the last successfully persisted event. No cursor update occurs
        when no events are processed.

        Returns:
            Number of events synced, or None if skipped.
        """
        semaphore = self.network_semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return None

        async with semaphore:
            if not self.is_running:
                return None
            max_duration = self._config.timeouts.max_duration
            if max_duration is not None and time.monotonic() - phase_start > max_duration:
                return None

            network_config = self._config.networks.get(relay.network)
            request_timeout = network_config.timeout
            relay_timeout = self._config.timeouts.get_relay_timeout(relay.network)

            start = self._get_start_time(relay, cursors)
            end_time = self._config.get_end_time()
            if start >= end_time:
                return None

            events_synced, cursor = await asyncio.wait_for(
                self._fetch_and_insert(relay, start, end_time, request_timeout),
                timeout=relay_timeout,
            )

            if cursor is not None:
                await self._queue_cursor_update(cursor_updates, cursor_lock, cursor)

            return events_synced

    async def _fetch_and_insert(
        self,
        relay: Relay,
        start_time: int,
        end_time: int,
        request_timeout: float,
    ) -> tuple[int, SyncCursor | None]:
        """Connect to a relay, stream events, and insert them.

        Manages the nostr-sdk client lifecycle and consumes the
        [stream_events][bigbrotr.services.synchronizer.utils.stream_events]
        async generator. Events are buffered and inserted in batches for
        efficiency.

        The cursor is set to ``end_time`` when all events are fetched
        successfully, or to the ``created_at`` of the last persisted event
        on partial completion (error or shutdown). Returns ``None`` when no
        events are processed.

        Args:
            relay: Target relay.
            start_time: Inclusive lower timestamp bound.
            end_time: Inclusive upper timestamp bound.
            request_timeout: Seconds per WebSocket fetch call.

        Returns:
            Tuple of (events_synced, cursor).
        """
        proxy_url = self._config.networks.get_proxy_url(relay.network)
        client = await connect_relay(
            relay,
            keys=self._keys,
            proxy_url=proxy_url,
            timeout=request_timeout,
            allow_insecure=self._config.allow_insecure,
        )

        filters = self._config.filters
        events_synced = 0
        cursor: SyncCursor | None = None
        buffer: list[Event] = []

        try:
            async for event in stream_events(
                client,
                filters,
                start_time,
                end_time,
                self._config.limit,
                request_timeout,
            ):
                buffer.append(event)

                if len(buffer) >= self._config.limit:
                    events_synced += await insert_events(buffer, relay, self._brotr)
                    last_ts = buffer[-1].created_at().as_secs()
                    cursor = SyncCursor(
                        key=relay.url,
                        timestamp=last_ts,
                        id=_CURSOR_SENTINEL_ID,
                    )
                    buffer.clear()

            # Flush remaining buffer
            if buffer:
                events_synced += await insert_events(buffer, relay, self._brotr)
                buffer.clear()

            # Generator completed — all events in [start_time, end_time] fetched
            cursor = SyncCursor(
                key=relay.url,
                timestamp=end_time,
                id=_CURSOR_SENTINEL_ID,
            )
            await client.disconnect()
        except (TimeoutError, OSError, NostrSdkError) as e:
            self._logger.warning("sync_relay_error", relay=relay.url, error=str(e))
        finally:
            try:
                await client.shutdown()
            except Exception as e:
                self._logger.debug("client_shutdown_error", relay=relay.url, error=str(e))

        return events_synced, cursor

    # ── Helpers ────────────────────────────────────────────────────

    def _get_start_time(self, relay: Relay, cursors: dict[str, SyncCursor]) -> int:
        """Look up the sync start timestamp from a pre-fetched cursor cache."""
        cursor = cursors.get(relay.url)
        if cursor is not None and cursor.timestamp is not None:
            return cursor.timestamp + 1

        return self._config.since

    async def _queue_cursor_update(
        self,
        cursor_updates: list[ServiceState],
        cursor_lock: asyncio.Lock,
        cursor: SyncCursor,
    ) -> None:
        """Add a cursor update to the buffer, flushing if interval reached."""
        async with cursor_lock:
            cursor_updates.append(
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.CURSOR,
                    state_key=cursor.key,
                    state_value={
                        "timestamp": cursor.timestamp,
                        "id": cursor.id.hex() if cursor.id else None,
                    },
                )
            )
            if len(cursor_updates) >= self._config.flush_interval:
                await self._flush_cursors(cursor_updates)

    async def _flush_cursors(self, cursor_updates: list[ServiceState]) -> None:
        """Flush pending cursor updates to the database and clear the buffer."""
        if not cursor_updates:
            return
        try:
            await upsert_service_states(self._brotr, cursor_updates)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.error(
                "cursor_flush_failed",
                error=str(e),
                count=len(cursor_updates),
            )
        cursor_updates.clear()
