"""Synchronizer service for BigBrotr.

Collects Nostr events from validated relays and stores them in the database.
Uses ``asyncio.TaskGroup`` with per-network semaphores for structured, bounded concurrency.

The synchronization workflow proceeds as follows:

1. Fetch sync cursors for all relays via
   [fetch_cursors_to_sync][bigbrotr.services.synchronizer.queries.fetch_cursors_to_sync],
   ordered by sync progress ascending (most behind first).
2. Connect to each relay and stream events since the last sync timestamp.
3. Insert pre-validated events (filtering, signature verification, and
   deduplication are handled at the fetch layer by ``_fetch_validated``)
   using a global buffer flushed at ``processing.batch_size``.
4. Update per-relay cursors in batch after each buffer flush, derived from
   the last event seen per relay in that batch.

Note:
    Workers yield ``(Event, Relay)`` pairs. The parent accumulates them into
    a global buffer and flushes to the database when the buffer reaches
    ``processing.batch_size``. At each flush, per-relay cursors are
    computed from the last event per relay in the buffer and persisted
    alongside the events. This bounds memory regardless of concurrent relay
    count and minimises DB round-trips.

    Cursor-based pagination ensures each relay is synced incrementally.
    Cursors are persisted in batch after every buffer flush and after the
    post-loop flush, so a crash never loses more than one batch of progress.

    Relays are processed in sync-progress order (most behind first) so that
    the most stale relays receive priority.

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

    brotr = Brotr.from_yaml("deployments/bigbrotr/config/brotr.yaml")
    sync = Synchronizer.from_yaml(
        "deployments/bigbrotr/config/services/synchronizer.yaml",
        brotr=brotr,
    )

    async with brotr:
        async with sync:
            await sync.run_forever()
    ```
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.mixins import ConcurrentStreamMixin, NetworkSemaphoresMixin
from bigbrotr.utils.protocol import NostrClientManager
from bigbrotr.utils.streaming import stream_events

from .configs import SynchronizerConfig
from .queries import (
    count_cursors_to_sync,
    delete_stale_cursors,
    insert_event_relays,
    iter_cursors_to_sync_pages,
    upsert_sync_cursors,
)
from .runtime import (
    SyncBatchState,
    SyncPageContext,
    SyncWorkerContext,
    build_sync_cycle_plan,
    flush_sync_batch,
    synchronize_cursor_page,
    synchronize_worker,
)
from .runtime import (
    SyncCyclePlan as SynchronizerCyclePlan,
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from types import TracebackType

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Event, EventRelay, Relay
    from bigbrotr.services.common.types import SyncCursor


class Synchronizer(
    ConcurrentStreamMixin,
    NetworkSemaphoresMixin,
    BaseService[SynchronizerConfig],
):
    """Event synchronization service.

    Collects Nostr events from validated relays and stores them in the
    database. Uses ``asyncio.TaskGroup`` with per-network semaphores for
    structured, bounded concurrency.

    Each cycle fetches sync cursors for all relays in a single query
    (LEFT JOIN), ordered by sync progress ascending so the most stale
    relays are processed first. Workers stream ``(Event, Relay)`` pairs
    and the parent batch-inserts events using a global buffer flushed at
    ``processing.batch_size``. Per-relay cursors are derived from
    the last event seen per relay in each batch and persisted at flush
    time for crash resilience.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Configuration model for this service.
        [Monitor][bigbrotr.services.monitor.Monitor]: Upstream service
            that health-checks relays before they are synced.
        [Finder][bigbrotr.services.finder.Finder]: Downstream consumer
            that discovers relay URLs from the events collected here.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.SYNCHRONIZER
    CONFIG_CLASS: ClassVar[type[SynchronizerConfig]] = SynchronizerConfig
    SyncCyclePlan = SynchronizerCyclePlan

    def __init__(
        self,
        brotr: Brotr,
        config: SynchronizerConfig | None = None,
    ) -> None:
        config = config or SynchronizerConfig()
        super().__init__(brotr=brotr, config=config, networks=config.networks)
        self._config: SynchronizerConfig
        self._keys: Keys = self._config.keys.keys
        self._client_manager = NostrClientManager(
            keys=self._keys,
            networks=self._config.networks,
            allow_insecure=self._config.processing.allow_insecure,
        )

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        await self._client_manager.disconnect()
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
        await self.synchronize()

    async def cleanup(self) -> int:
        """Remove stale cursor state for relays that no longer exist."""
        return await delete_stale_cursors(self._brotr)

    async def _build_sync_cycle_plan(self) -> SynchronizerCyclePlan | None:
        """Compute the enabled networks and batching budget for one cycle."""
        return await build_sync_cycle_plan(
            brotr=self._brotr,
            config=self._config,
            network_semaphores=self.network_semaphores,
            count_cursors=count_cursors_to_sync,
        )

    async def synchronize(self) -> int:
        """Fetch cursors and sync events from all relays concurrently.

        Fetches sync cursors for enabled networks in a single query, ordered
        by sync progress ascending (most behind first). Workers yield
        ``(Event, Relay)`` pairs. The parent accumulates them into a global
        buffer and flushes to the database at ``processing.batch_size``.
        Per-relay cursors are derived from the last event seen and persisted
        at each flush.

        Returns:
            Total events synced across all relays.
        """
        plan = await self._build_sync_cycle_plan()
        if plan is None:
            self._logger.warning("no_networks_enabled")
            return 0

        events_synced = 0
        buffer: list[EventRelay] = []
        pending_cursors: dict[str, SyncCursor] = {}

        self.set_gauge("total_relays", plan.total_relays)
        self.set_gauge("relays_seen", 0)
        self.set_gauge("events_seen", 0)

        self._logger.info("sync_started", relay_count=plan.total_relays)

        timed_out = False
        async for cursors in iter_cursors_to_sync_pages(
            self._brotr,
            plan.end_time,
            list(plan.networks),
            page_size=plan.page_size,
        ):
            page_events_synced, timed_out = await self._synchronize_cursor_page(
                cursors,
                buffer,
                pending_cursors,
                plan=plan,
            )
            events_synced += page_events_synced
            if timed_out:
                break

        events_synced += await self._flush_sync_batch(buffer, pending_cursors)

        self._logger.info(
            "sync_completed",
            events_synced=events_synced,
        )
        return events_synced

    async def _synchronize_cursor_page(
        self,
        cursors: list[SyncCursor],
        buffer: list[EventRelay],
        pending_cursors: dict[str, SyncCursor],
        *,
        plan: SynchronizerCyclePlan,
    ) -> tuple[int, bool]:
        """Scan one page of relay cursors and flush when the batch budget is reached."""
        return await synchronize_cursor_page(
            cursors=cursors,
            batch_state=SyncBatchState(
                buffer=buffer,
                pending_cursors=pending_cursors,
            ),
            plan=plan,
            context=SyncPageContext(
                iter_concurrent=self._iter_concurrent,
                worker=self._synchronize_worker,
                flush_batch=self._flush_sync_batch,
                inc_gauge=self.inc_gauge,
                logger=self._logger,
            ),
        )

    async def _flush_sync_batch(
        self,
        buffer: list[EventRelay],
        pending_cursors: dict[str, SyncCursor],
    ) -> int:
        """Persist one accumulated sync batch and clear in-memory state."""
        return await flush_sync_batch(
            self._brotr,
            buffer,
            pending_cursors,
            insert_event_relays_fn=insert_event_relays,
            upsert_sync_cursors_fn=upsert_sync_cursors,
        )

    # ── Workers ────────────────────────────────────────────────────

    async def _synchronize_worker(
        self, cursor: SyncCursor
    ) -> AsyncGenerator[tuple[Event, Relay], None]:
        """Stream events from a single relay for use with ``_iter_concurrent``.

        Acquires the per-network semaphore, connects to the relay, and streams
        events. Each yielded pair is ``(Event, Relay)``.
        """
        async for item in synchronize_worker(
            context=SyncWorkerContext(
                network_semaphores=self.network_semaphores,
                logger=self._logger,
                is_running=lambda: self.is_running,
                config=self._config,
                client_manager=self._client_manager,
                stream_events_fn=stream_events,
                inc_gauge=self.inc_gauge,
            ),
            cursor=cursor,
        ):
            yield item
