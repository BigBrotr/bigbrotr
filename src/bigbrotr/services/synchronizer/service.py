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
import random
import time
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import NetworkSemaphoreMixin
from bigbrotr.services.common.queries import get_all_relays, get_all_service_cursors

from .configs import SynchronizerConfig
from .utils import SyncBatchState, SyncContext, sync_relay_events


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr


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
        self._synced_events: int = 0
        self._synced_relays: int = 0
        self._failed_relays: int = 0
        self._invalid_events: int = 0
        self._skipped_events: int = 0

        self._keys: Keys = self._config.keys.keys  # For NIP-42 authentication

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
        self.init_semaphores(self._config.networks)
        cycle_start = time.monotonic()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0
        self._invalid_events = 0
        self._skipped_events = 0

        relays = await self.fetch_relays()

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
        cursors = await self.fetch_cursors()
        batch = SyncBatchState(
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
        self, relay: Relay, cursors: dict[str, int], batch: SyncBatchState
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
        semaphore = self.get_semaphore(relay.network)
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
                    sync_relay_events(relay=relay, start_time=start, end_time=end_time, ctx=ctx),
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

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def fetch_relays(self) -> list[Relay]:
        """Fetch validated relays from the database for synchronization.

        Returns:
            List of relays to sync.

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

    async def fetch_cursors(self) -> dict[str, int]:
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
