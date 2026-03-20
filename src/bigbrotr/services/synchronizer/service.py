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

    brotr = Brotr.from_yaml("config/brotr.yaml")
    sync = Synchronizer.from_yaml("config/services/synchronizer.yaml", brotr=brotr)

    async with brotr:
        async with sync:
            await sync.run_forever()
    ```
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from nostr_sdk import NostrSdkError

from bigbrotr.core.base_service import BaseService
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.mixins import ConcurrentStreamMixin, NetworkSemaphoresMixin
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.utils.protocol import connect_relay
from bigbrotr.utils.streaming import stream_events

from .configs import SynchronizerConfig
from .queries import (
    delete_stale_cursors,
    fetch_cursors_to_sync,
    insert_event_relays,
    upsert_sync_cursors,
)


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from nostr_sdk import Keys

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Event


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

    def __init__(
        self,
        brotr: Brotr,
        config: SynchronizerConfig | None = None,
    ) -> None:
        config = config or SynchronizerConfig()
        super().__init__(brotr=brotr, config=config, networks=config.networks)
        self._config: SynchronizerConfig
        self._keys: Keys = self._config.keys.keys

    async def run(self) -> None:
        """Execute one complete synchronization cycle across all relays."""
        await self.synchronize()

    async def cleanup(self) -> int:
        """Remove stale cursor state for relays that no longer exist."""
        return await delete_stale_cursors(self._brotr)

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
        networks = self._config.networks.get_enabled_networks()
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        end_time = self._config.processing.get_end_time()
        cursors = await fetch_cursors_to_sync(self._brotr, end_time, networks)

        events_synced = 0
        buffer: list[EventRelay] = []
        pending_cursors: dict[str, SyncCursor] = {}
        batch_size = self._config.processing.batch_size

        self.set_gauge("total_relays", len(cursors))
        self.set_gauge("relays_seen", 0)
        self.set_gauge("events_seen", 0)

        deadline = time.monotonic() + self._config.timeouts.max_duration

        self._logger.info("sync_started", relay_count=len(cursors))

        async for event, relay in self._iter_concurrent(cursors, self._synchronize_worker):
            buffer.append(EventRelay(event, relay))
            pending_cursors[relay.url] = SyncCursor(
                key=relay.url,
                timestamp=event.created_at().as_secs(),
                id=event.id().to_hex(),
            )
            self.inc_gauge("events_seen")
            if len(buffer) == batch_size:
                events_synced += await insert_event_relays(self._brotr, buffer)
                buffer = []
                await upsert_sync_cursors(self._brotr, pending_cursors.values())
                pending_cursors = {}
                if time.monotonic() > deadline:
                    self._logger.info("sync_timeout", events_synced=events_synced)
                    break

        if buffer:
            events_synced += await insert_event_relays(self._brotr, buffer)
        if pending_cursors:
            await upsert_sync_cursors(self._brotr, pending_cursors.values())

        self._logger.info(
            "sync_completed",
            events_synced=events_synced,
        )
        return events_synced

    # ── Workers ────────────────────────────────────────────────────

    async def _synchronize_worker(
        self, cursor: SyncCursor
    ) -> AsyncGenerator[tuple[Event, Relay], None]:
        """Stream events from a single relay for use with ``_iter_concurrent``.

        Acquires the per-network semaphore, connects to the relay, and streams
        events. Each yielded pair is ``(Event, Relay)``.
        """
        relay = Relay(cursor.key)
        try:
            semaphore = self.network_semaphores.get(relay.network)
            if semaphore is None:
                self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
                return

            async with semaphore:
                if not self.is_running:
                    return

                network_config = self._config.networks.get(relay.network)
                request_timeout = network_config.timeout

                try:
                    client = await connect_relay(
                        relay,
                        keys=self._keys,
                        proxy_url=self._config.networks.get_proxy_url(relay.network),
                        timeout=request_timeout,
                        allow_insecure=self._config.processing.allow_insecure,
                    )
                except (OSError, TimeoutError) as e:
                    self._logger.warning("connect_failed", relay=relay.url, error=str(e))
                    return

                try:
                    async for event in stream_events(
                        client,
                        self._config.processing.filters,
                        cursor.timestamp,
                        self._config.processing.get_end_time(),
                        self._config.processing.limit,
                        request_timeout,
                        self._config.timeouts.idle,
                    ):
                        yield event, relay

                    await client.disconnect()

                except (TimeoutError, OSError, NostrSdkError) as e:
                    self._logger.warning("sync_relay_error", relay=relay.url, error=str(e))
                finally:
                    self.inc_gauge("relays_seen")
                    try:
                        await client.shutdown()
                    except Exception as e:  # nostr-sdk FFI can raise arbitrary errors on shutdown
                        self._logger.debug("client_shutdown_error", relay=relay.url, error=str(e))
        except Exception as e:  # Worker exception boundary — protects TaskGroup
            self._logger.error(
                "sync_worker_failed",
                error=str(e),
                error_type=type(e).__name__,
                relay=relay.url,
            )
