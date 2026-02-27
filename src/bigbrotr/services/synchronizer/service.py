"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Uses ``asyncio.TaskGroup`` with per-network semaphores for structured, bounded concurrency.

The synchronization workflow proceeds as follows:

1. Fetch relays from the database via
   [fetch_all_relays][bigbrotr.services.common.queries.fetch_all_relays]
   (optionally filtered by metadata age).
2. Load per-relay sync cursors from ``service_state`` via
   [Brotr.get_service_state][bigbrotr.core.brotr.Brotr.get_service_state].
3. Connect to each relay and fetch events since the last sync timestamp.
4. Validate event signatures and timestamps before insertion.
5. Update per-relay cursors for the next cycle.

Note:
    Cursor-based pagination ensures each relay is synced incrementally.
    The cursor (``last_synced_at``) is stored as a
    [ServiceState][bigbrotr.models.service_state.ServiceState] record
    with ``state_type='cursor'``. Cursor updates are batched (flushed
    every ``cursor_flush_interval`` relays) for crash resilience.

    Relay processing order is randomized (shuffled) to avoid
    thundering-herd effects when multiple synchronizer instances run
    concurrently.

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
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import NetworkSemaphoresMixin
from bigbrotr.services.common.queries import (
    cleanup_stale_state,
    fetch_all_relays,
)
from bigbrotr.services.common.types import EventRelayCursor

from .configs import RelayOverride, SynchronizerConfig
from .utils import SyncBatchState, SyncContext, SyncCycleCounters, sync_relay_events


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr


class Synchronizer(NetworkSemaphoresMixin, BaseService[SynchronizerConfig]):
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
        self._counters = SyncCycleCounters()
        self._keys: Keys = self._config.keys.keys  # For NIP-42 authentication

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays.

        Orchestrates counter reset, synchronization, and cycle-level logging.
        Delegates the core work to ``synchronize``.
        """
        self._logger.info(
            "cycle_started",
            from_database=self._config.source.from_database,
            overrides=len(self._config.overrides),
        )

        cycle_start = time.monotonic()
        self._counters.reset()

        relay_count = await self.synchronize()

        self.set_gauge("total", relay_count)
        self.set_gauge("synced_relays", self._counters.synced_relays)
        self.set_gauge("failed_relays", self._counters.failed_relays)
        self.set_gauge("synced_events", self._counters.synced_events)
        self.set_gauge("invalid_events", self._counters.invalid_events)

        self._logger.info(
            "cycle_completed",
            synced_relays=self._counters.synced_relays,
            failed_relays=self._counters.failed_relays,
            synced_events=self._counters.synced_events,
            invalid_events=self._counters.invalid_events,
            duration_s=round(time.monotonic() - cycle_start, 2),
        )

    async def synchronize(self) -> int:
        """Fetch relays, merge overrides, and sync events from all of them.

        High-level entry point that fetches relays from the database,
        merges configured relay overrides, shuffles the list to avoid
        thundering-herd effects, and syncs all relays concurrently.

        This is the method ``run()`` delegates to. It can also be called
        standalone without cycle-level logging or counter reset.

        Returns:
            Number of relays that were processed.
        """
        try:
            removed = await cleanup_stale_state(
                self._brotr, self.SERVICE_NAME, ServiceStateType.CURSOR
            )
            if removed:
                self._logger.info("stale_cursors_removed", count=removed)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning(
                "stale_cursor_cleanup_failed", error=str(e), error_type=type(e).__name__
            )

        relays = await self.fetch_relays()
        relays = self._merge_overrides(relays)

        if not relays:
            self._logger.info("no_relays_to_sync")
            return 0

        self._logger.info("sync_started", relay_count=len(relays))
        random.shuffle(relays)
        await self._sync_all_relays(relays)
        return len(relays)

    async def fetch_relays(self) -> list[Relay]:
        """Fetch validated relays from the database for synchronization.

        Filters relays to only include enabled networks, avoiding unnecessary
        relay loading for disabled network types.

        Controlled by ``source.from_database`` in
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig].

        Returns:
            List of relays to sync (filtered by enabled networks).

        See Also:
            [fetch_all_relays][bigbrotr.services.common.queries.fetch_all_relays]:
                The SQL query executed by this method.
        """
        if not self._config.source.from_database:
            return []

        all_relays = await fetch_all_relays(self._brotr)
        enabled = set(self._config.networks.get_enabled_networks())
        relays = [r for r in all_relays if r.network in enabled]

        self._logger.debug("relays_fetched", count=len(relays))
        return relays

    async def fetch_cursors(self) -> dict[str, EventRelayCursor]:
        """Batch-fetch all relay sync cursors in a single query.

        Controlled by ``time_range.use_relay_state`` in
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig].

        Returns:
            Dict mapping relay URL to
            [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor].
        """
        if not self._config.time_range.use_relay_state:
            return {}

        states = await self._brotr.get_service_state(self.SERVICE_NAME, ServiceStateType.CURSOR)
        return {
            s.state_key: EventRelayCursor(
                relay_url=s.state_key, seen_at=s.state_value["last_synced_at"]
            )
            for s in states
            if "last_synced_at" in s.state_value
        }

    def _merge_overrides(self, relays: list[Relay]) -> list[Relay]:
        """Merge configured relay overrides into the relay list.

        Adds any override URLs not already present in the list.
        """
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
        return relays

    async def _sync_all_relays(self, relays: list[Relay]) -> None:
        """Sync all relays concurrently using structured concurrency.

        Uses ``asyncio.TaskGroup`` with per-network semaphores to bound
        simultaneous WebSocket connections. Cursor updates are batched and
        flushed every ``cursor_flush_interval`` relays for crash resilience.
        """
        cursors = await self.fetch_cursors()
        batch = SyncBatchState(
            cursor_updates=[],
            cursor_lock=asyncio.Lock(),
            cursor_flush_interval=self._config.concurrency.cursor_flush_interval,
        )
        overrides_map: dict[str, RelayOverride] = {o.url: o for o in self._config.overrides}

        try:
            async with asyncio.TaskGroup() as tg:
                for relay in relays:
                    tg.create_task(self._sync_single_relay(relay, cursors, batch, overrides_map))
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                self._logger.error(
                    "worker_unexpected_exception",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self._counters.failed_relays += 1

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
        self,
        relay: Relay,
        cursors: dict[str, EventRelayCursor],
        batch: SyncBatchState,
        overrides_map: dict[str, RelayOverride],
    ) -> None:
        """Sync events from a single relay with semaphore-bounded concurrency."""
        semaphore = self.network_semaphores.get(relay.network)
        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return

        async with semaphore:
            network_type_config = self._config.networks.get(relay.network)
            request_timeout = network_type_config.timeout
            relay_timeout = self._config.timeouts.get_relay_timeout(relay.network)

            override = overrides_map.get(str(relay.url))
            if override is not None:
                if override.timeouts.relay is not None:
                    relay_timeout = override.timeouts.relay
                if override.timeouts.request is not None:
                    request_timeout = override.timeouts.request

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
                events_synced, invalid_events = await asyncio.wait_for(
                    sync_relay_events(relay=relay, start_time=start, end_time=end_time, ctx=ctx),
                    timeout=relay_timeout,
                )

                async with self._counters.lock:
                    self._counters.synced_events += events_synced
                    self._counters.invalid_events += invalid_events
                    self._counters.synced_relays += 1

                self.inc_counter("total_events_synced", events_synced)
                self.inc_counter("total_events_invalid", invalid_events)

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
                async with self._counters.lock:
                    self._counters.failed_relays += 1

    def _get_start_time_from_cache(self, relay: Relay, cursors: dict[str, EventRelayCursor]) -> int:
        """Look up the sync start timestamp from a pre-fetched cursor cache."""
        if not self._config.time_range.use_relay_state:
            return self._config.time_range.default_start

        cursor = cursors.get(relay.url)
        if cursor is not None and cursor.seen_at is not None:
            return cursor.seen_at + 1

        return self._config.time_range.default_start
