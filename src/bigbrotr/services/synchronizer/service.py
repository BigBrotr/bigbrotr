"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Uses ``asyncio.TaskGroup`` with per-network semaphores for structured, bounded concurrency.

The synchronization workflow proceeds as follows:

1. Fetch relays from the database via
   [fetch_relays][bigbrotr.services.common.queries.fetch_relays]
   (optionally filtered by metadata age).
2. Load per-relay sync cursors from ``service_state`` via
   [Brotr.get_service_state][bigbrotr.core.brotr.Brotr.get_service_state].
3. Connect to each relay and fetch events since the last sync timestamp.
4. Validate event signatures and timestamps before insertion.
5. Update per-relay cursors for the next cycle.

Note:
    Cursor-based pagination ensures each relay is synced incrementally.
    The cursor (``timestamp``) is stored as a
    [ServiceState][bigbrotr.models.service_state.ServiceState] record
    with ``state_type='cursor'``.  Cursor updates are batched (flushed
    every ``cursor_flush_interval`` relays) for crash resilience.

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
    [create_client][bigbrotr.utils.protocol.create_client]: Factory for
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
import random
import time
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import NetworkSemaphoresMixin
from bigbrotr.services.common.queries import upsert_service_states

from .configs import SynchronizerConfig
from .queries import delete_stale_cursors, fetch_relays
from .utils import SyncBatchState, SyncContext, sync_relay_events


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Synchronizer(
    NetworkSemaphoresMixin,
    BaseService[SynchronizerConfig],
):
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
        return await delete_stale_cursors(self)

    async def synchronize(self) -> int:
        """Fetch relays and sync events from all of them.

        Returns:
            Total events synced across all relays.
        """
        relays = await self.fetch_relays()

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
        if not self._config.source.from_database:
            return []

        all_relays = await fetch_relays(self._brotr)
        enabled = set(self._config.networks.get_enabled_networks())
        relays = [r for r in all_relays if r.network in enabled]

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def fetch_cursors(self) -> dict[str, int]:
        """Batch-fetch all relay sync cursors in a single query.

        Returns:
            Dict mapping relay URL to sync timestamp.
        """
        if not self._config.time_range.use_relay_state:
            return {}

        states = await self._brotr.get_service_state(self.SERVICE_NAME, ServiceStateType.CURSOR)
        cursors: dict[str, int] = {}
        for s in states:
            if "timestamp" not in s.state_value:
                continue
            try:
                cursors[s.state_key] = int(s.state_value["timestamp"])
            except (ValueError, TypeError) as e:
                self._logger.warning("invalid_cursor_data", relay=s.state_key, error=str(e))
        return cursors

    # ── Sync orchestration ────────────────────────────────────────

    async def _run_sync(
        self,
        relays: list[Relay],
        cursors: dict[str, int],
    ) -> int:
        """Sync all relays concurrently and aggregate results.

        Uses ``asyncio.TaskGroup`` with per-network semaphores to bound
        simultaneous WebSocket connections. Cursor updates are batched and
        flushed every ``cursor_flush_interval`` relays for crash resilience.

        Returns:
            Total events synced.
        """
        cursor_batch = SyncBatchState(
            cursor_updates=[],
            cursor_lock=asyncio.Lock(),
            cursor_flush_interval=self._config.concurrency.cursor_flush_interval,
        )

        phase_start = time.monotonic()
        tasks: list[asyncio.Task[tuple[int, int] | None]] = []
        try:
            async with asyncio.TaskGroup() as tg:
                tasks.extend(
                    tg.create_task(
                        self._sync_single_relay(relay, cursors, cursor_batch, phase_start)
                    )
                    for relay in relays
                )
        except ExceptionGroup:
            pass  # Individual errors are logged in the task loop below

        await self._flush_cursor_batch(cursor_batch)

        total_events = 0
        total_invalid = 0
        relays_scanned = 0
        scan_failures = 0

        for task in tasks:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                self._logger.error(
                    "sync_worker_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                scan_failures += 1
                continue
            result = task.result()
            if result is None:
                continue
            events, invalid = result
            total_events += events
            total_invalid += invalid
            relays_scanned += 1

        self.set_gauge("events_synced", total_events)
        self.set_gauge("relays_scanned", relays_scanned)
        self.inc_counter("total_events_synced", total_events)
        self.inc_counter("total_events_invalid", total_invalid)
        self.inc_counter("total_sync_failures", scan_failures)

        self._logger.info(
            "sync_completed",
            events_synced=total_events,
            events_invalid=total_invalid,
            relays_scanned=relays_scanned,
            scan_failures=scan_failures,
        )
        return total_events

    async def _sync_single_relay(
        self,
        relay: Relay,
        cursors: dict[str, int],
        cursor_batch: SyncBatchState,
        phase_start: float,
    ) -> tuple[int, int] | None:
        """Sync events from a single relay with semaphore-bounded concurrency.

        Returns:
            Tuple of (events_synced, invalid_events), or None if skipped.
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
            end_time = int(time.time()) - self._config.time_range.lookback_seconds
            if start >= end_time:
                return None

            ctx = SyncContext(
                filter_config=self._config.filter,
                network_config=self._config.networks,
                request_timeout=request_timeout,
                brotr=self._brotr,
                keys=self._keys,
            )

            events_synced, invalid_events = await asyncio.wait_for(
                sync_relay_events(relay=relay, start_time=start, end_time=end_time, ctx=ctx),
                timeout=relay_timeout,
            )

            await self._batch_cursor_update(cursor_batch, relay, end_time)
            return events_synced, invalid_events

    # ── Helpers ────────────────────────────────────────────────────

    def _get_start_time(self, relay: Relay, cursors: dict[str, int]) -> int:
        """Look up the sync start timestamp from a pre-fetched cursor cache."""
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        cursor_ts = cursors.get(relay.url)
        if cursor_ts is not None:
            return cursor_ts + 1

        return self._config.time_range.default_start

    async def _batch_cursor_update(
        self, batch: SyncBatchState, relay: Relay, end_time: int
    ) -> None:
        """Add a cursor update to the batch, flushing if interval reached."""
        async with batch.cursor_lock:
            batch.cursor_updates.append(
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.CURSOR,
                    state_key=relay.url,
                    state_value={"timestamp": end_time},
                )
            )
            if len(batch.cursor_updates) >= batch.cursor_flush_interval:
                try:
                    await upsert_service_states(self._brotr, batch.cursor_updates.copy())
                except (asyncpg.PostgresError, OSError) as e:
                    self._logger.error(
                        "cursor_batch_flush_failed",
                        error=str(e),
                        count=len(batch.cursor_updates),
                    )
                batch.cursor_updates.clear()

    async def _flush_cursor_batch(self, batch: SyncBatchState) -> None:
        """Flush remaining cursor updates after all relays are processed."""
        if not batch.cursor_updates:
            return
        try:
            await upsert_service_states(self._brotr, batch.cursor_updates)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.error(
                "cursor_batch_upsert_failed",
                error=str(e),
                count=len(batch.cursor_updates),
            )
