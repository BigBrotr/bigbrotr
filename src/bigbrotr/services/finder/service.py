"""Finder service for BigBrotr.

Discovers Nostr relay URLs from two sources:

1. **External APIs** -- Public endpoints like nostr.watch that list relays.
   Each API source declares how relay URLs are extracted from its JSON
   response (flat array, nested path, object keys, etc.) via
   [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig].
2. **Database events** -- Tag values from all stored events are parsed via
   [try_parse_relay][bigbrotr.services.common.utils.try_parse_relay]; only
   valid ``wss://`` / ``ws://`` URLs pass validation. This is kind-agnostic:
   any event whose ``tagvalues`` column contains relay-like strings will
   contribute discovered URLs.

Discovered URLs are inserted as validation candidates for the
[Validator][bigbrotr.services.validator.Validator] service via
[insert_relays_as_candidates][bigbrotr.services.common.discovery_queries.insert_relays_as_candidates].

Note:
    Event scanning uses per-relay cursor-based pagination so that
    historical events inserted by the
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] are
    eventually processed. Cursors are stored as
    [ServiceState][bigbrotr.models.service_state.ServiceState] records
    with ``state_type='cursor'`` and a composite ``(timestamp, id)``
    cursor in ``state_value`` for deterministic resumption.

See Also:
    [FinderConfig][bigbrotr.services.finder.FinderConfig]: Configuration
        model for API sources, event scanning, and concurrency.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for
        event queries and candidate insertion.
    [Seeder][bigbrotr.services.seeder.Seeder]: Upstream service that
        bootstraps initial relay URLs.
    [Validator][bigbrotr.services.validator.Validator]: Downstream
        service that validates the candidates discovered here.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Finder

    brotr = Brotr.from_yaml("deployments/bigbrotr/config/brotr.yaml")
    finder = Finder.from_yaml("deployments/bigbrotr/config/services/finder.yaml", brotr=brotr)

    async with brotr:
        async with finder:
            await finder.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, ClassVar

import aiohttp

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.discovery_queries import insert_relays_as_candidates
from bigbrotr.services.common.mixins import ConcurrentStreamMixin

from .api_runtime import (
    ApiSourceAttempt,
    build_api_source_attempts,
    stream_api_discovery_attempts,
)
from .configs import ApiSourceConfig, FinderConfig
from .event_runtime import (
    EventScanPageContext,
    EventScanPersistenceContext,
    EventWorkerContext,
    build_event_scan_plan,
    flush_event_scan_batch,
    scan_event_cursor_page,
    stream_event_discovery_worker,
)
from .event_runtime import (
    EventScanPlan as FinderEventScanPlan,
)
from .queries import (
    count_relays_to_find,
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_api_checkpoints,
    iter_cursors_to_find_pages,
    upsert_api_checkpoints,
    upsert_finder_cursors,
)
from .utils import extract_relays_from_tagvalues, fetch_api, stream_event_relays


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.services.common.types import ApiCheckpoint, FinderCursor


class Finder(ConcurrentStreamMixin, BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the
        [Validator][bigbrotr.services.validator.Validator] service via
        [insert_relays_as_candidates][bigbrotr.services.common.discovery_queries.insert_relays_as_candidates].

    See Also:
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Configuration
            model for this service.
        [Seeder][bigbrotr.services.seeder.Seeder]: Upstream service that
            provides initial seed URLs.
        [Validator][bigbrotr.services.validator.Validator]: Downstream
            service that validates discovered candidates.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.FINDER
    CONFIG_CLASS: ClassVar[type[FinderConfig]] = FinderConfig
    EventScanPlan = FinderEventScanPlan

    def __init__(
        self,
        brotr: Brotr,
        config: FinderConfig | None = None,
    ) -> None:
        config = config or FinderConfig()
        super().__init__(brotr=brotr, config=config)
        self._config: FinderConfig

    async def run(self) -> None:
        """Execute a single discovery cycle across all configured sources."""
        await self.find()

    async def cleanup(self) -> int:
        """Remove stale state: orphaned relay cursors and obsolete API checkpoints."""
        removed = await delete_stale_cursors(self._brotr)
        active_urls = [s.url for s in self._config.api.sources]
        removed += await delete_stale_api_checkpoints(self._brotr, active_urls)
        return removed

    async def find(self) -> int:
        """Discover relay URLs from all configured sources.

        Runs API fetching first (fast), then event scanning (slow),
        respecting the ``api.enabled`` and ``events.enabled`` configuration
        flags. Returns the total number of relay URLs inserted as candidates.

        Returns:
            Total number of relay URLs discovered and inserted.
        """
        found = 0
        found += await self.find_from_api()
        found += await self.find_from_events()
        return found

    # ── API discovery ──────────────────────────────────────────────

    async def find_from_api(self) -> int:
        """Discover relay URLs from configured external API endpoints.

        Delegates fetching to ``_find_from_api_worker``, which iterates
        all enabled sources sequentially. The parent saves updated
        checkpoints and inserts discovered URLs as candidates.

        Returns:
            Number of relay URLs inserted as candidates.
        """
        if not self._config.api.enabled:
            return 0
        sources = tuple(source for source in self._config.api.sources if source.enabled)

        buffer: list[Relay] = []
        pending_checkpoints: list[ApiCheckpoint] = []

        self.set_gauge("total_sources", len(sources))
        self.set_gauge("sources_fetched", 0)
        self.set_gauge("candidates_found_from_api", 0)

        self._logger.info("api_started", source_count=len(sources))

        async for relays, checkpoint in self._find_from_api_worker(list(sources)):
            buffer.extend(relays)
            pending_checkpoints.append(checkpoint)
            self.inc_gauge("sources_fetched")

        found = await self._persist_api_discovery_results(buffer, pending_checkpoints)

        self._logger.info("api_completed", found=found, collected=len(buffer))
        return found

    async def _persist_api_discovery_results(
        self,
        buffer: list[Relay],
        pending_checkpoints: list[ApiCheckpoint],
    ) -> int:
        """Persist one API discovery cycle and clear its in-memory state."""
        if pending_checkpoints:
            checkpoints_batch = list(pending_checkpoints)
            await upsert_api_checkpoints(self._brotr, checkpoints_batch)
            pending_checkpoints.clear()

        relays_batch = list(buffer)
        found = await insert_relays_as_candidates(self._brotr, relays_batch)
        self.set_gauge("candidates_found_from_api", found)
        buffer.clear()
        return found

    async def _find_from_api_worker(
        self,
        sources: list[ApiSourceConfig],
    ) -> AsyncGenerator[tuple[list[Relay], ApiCheckpoint], None]:
        """Iterate all enabled API sources sequentially.

        Loads per-source checkpoints, checks cooldown, fetches relay URLs,
        and yields ``(relays, checkpoint)`` with updated timestamp on success.
        Skipped (cooldown) and failed (network error) sources yield nothing.
        Respects ``request_delay`` between sources and ``is_running`` for
        graceful shutdown.
        """
        source_urls = [s.url for s in sources]
        checkpoints = await fetch_api_checkpoints(self._brotr, source_urls)
        checkpoint_map = {cp.key: cp for cp in checkpoints}
        async for relays, checkpoint in stream_api_discovery_attempts(
            sources,
            checkpoint_map,
            cooldown=int(self._config.api.cooldown),
            now=int(time.time()),
            max_response_size=self._config.api.max_response_size,
            request_delay=self._config.api.request_delay,
            is_running=lambda: self.is_running,
            wait=self.wait,
            fetch_api_fn=fetch_api,
            client_session_factory=aiohttp.ClientSession,
            recoverable_errors=(TimeoutError, OSError, aiohttp.ClientError, ValueError),
            checkpoint_timestamp=lambda: int(time.time()),
            logger=self._logger,
        ):
            yield relays, checkpoint

    def _build_api_source_attempts(
        self,
        sources: list[ApiSourceConfig],
        checkpoint_map: dict[str, ApiCheckpoint],
        now: int,
    ) -> tuple[ApiSourceAttempt, ...]:
        """Return the enabled API sources whose cooldown has elapsed for this cycle."""
        return build_api_source_attempts(
            sources,
            checkpoint_map,
            cooldown=int(self._config.api.cooldown),
            now=now,
            logger=self._logger,
        )

    # ── Event discovery ────────────────────────────────────────────

    async def find_from_events(self) -> int:
        """Discover relay URLs from stored events using cursor pagination.

        Fetches current cursor positions, scans all relays concurrently
        (bounded by ``events.parallel_relays``) via ``_iter_concurrent()``.
        Workers stream event-relay rows. The parent extracts relay URLs,
        accumulates them in a global buffer flushed at
        ``brotr.config.batch.max_size``, and saves cursors in batch after
        each flush.

        Returns:
            Number of relay URLs discovered and inserted as candidates.
        """
        if not self._config.events.enabled:
            return 0

        plan = await self._build_event_scan_plan()
        if plan is None:
            self._logger.debug("no_relays_to_scan")
            return 0

        self._event_semaphore = asyncio.Semaphore(self._config.events.parallel_relays)
        self._phase_start = plan.phase_start

        total_found = 0
        buffer: list[Relay] = []
        pending_cursors: dict[str, FinderCursor] = {}

        self.set_gauge("relays_seen", 0)
        self.set_gauge("rows_seen", 0)
        self.set_gauge("candidates_found_from_events", 0)

        self._logger.info("scan_started", relay_count=plan.relay_count)

        async for cursors in iter_cursors_to_find_pages(self._brotr, page_size=plan.page_size):
            total_found += await self._scan_event_cursor_page(
                cursors,
                buffer,
                pending_cursors,
                plan=plan,
            )

        total_found += await self._flush_event_scan_batch(buffer, pending_cursors)

        self._logger.info("scan_completed", found=total_found)
        return total_found

    async def _build_event_scan_plan(self) -> FinderEventScanPlan | None:
        """Compute the batching budget and progress totals for one event scan cycle."""
        return await build_event_scan_plan(
            brotr=self._brotr,
            config=self._config,
            count_relays_fn=count_relays_to_find,
            monotonic=time.monotonic,
        )

    async def _scan_event_cursor_page(
        self,
        cursors: list[FinderCursor],
        buffer: list[Relay],
        pending_cursors: dict[str, FinderCursor],
        *,
        plan: FinderEventScanPlan,
    ) -> int:
        """Scan one page of source relays and flush when the batch budget is reached."""
        return await scan_event_cursor_page(
            cursors=cursors,
            buffer=buffer,
            pending_cursors=pending_cursors,
            plan=plan,
            context=EventScanPageContext(
                iter_concurrent=self._iter_concurrent,
                worker=self._find_from_events_worker,
                flush_batch=self._flush_event_scan_batch,
                inc_gauge=self.inc_gauge,
            ),
        )

    async def _flush_event_scan_batch(
        self,
        buffer: list[Relay],
        pending_cursors: dict[str, FinderCursor],
    ) -> int:
        """Persist one accumulated event-scan batch and clear in-memory state."""
        return await flush_event_scan_batch(
            buffer=buffer,
            pending_cursors=pending_cursors,
            context=EventScanPersistenceContext(
                brotr=self._brotr,
                insert_relays_fn=insert_relays_as_candidates,
                upsert_cursors_fn=upsert_finder_cursors,
                inc_gauge=self.inc_gauge,
            ),
        )

    async def _find_from_events_worker(
        self, cursor: FinderCursor
    ) -> AsyncGenerator[tuple[list[Relay], FinderCursor], None]:
        """Stream discovered relays from a single source relay for ``_iter_concurrent``.

        Acquires the per-phase semaphore, streams rows via
        [stream_event_relays][bigbrotr.services.finder.utils.stream_event_relays],
        extracts relay URLs from tagvalues, and yields ``(relays, cursor)``
        pairs. On unexpected exception, logs and returns (the relay is silently
        skipped).
        """
        async for item in stream_event_discovery_worker(
            context=EventWorkerContext(
                event_semaphore=self._event_semaphore,
                is_running=lambda: self.is_running,
                phase_start=self._phase_start,
                max_duration=self._config.events.max_duration,
                max_relay_time=self._config.events.max_relay_time,
                scan_size=self._config.events.scan_size,
                brotr=self._brotr,
                logger=self._logger,
                stream_event_relays=stream_event_relays,
                extract_relays_from_tagvalues=extract_relays_from_tagvalues,
                monotonic=time.monotonic,
                inc_gauge=self.inc_gauge,
            ),
            cursor=cursor,
        ):
            yield item
