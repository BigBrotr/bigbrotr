"""Finder service for BigBrotr.

Discovers Nostr relay URLs from two sources:

1. **External APIs** -- Public endpoints like nostr.watch that list relays.
   Each API source declares how relay URLs are extracted from its JSON
   response (flat array, nested path, object keys, etc.) via
   [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig].
2. **Database events** -- Tag values from all stored events are parsed via
   [parse_relay][bigbrotr.services.common.utils.parse_relay]; only
   valid ``wss://`` / ``ws://`` URLs pass validation. This is kind-agnostic:
   any event whose ``tagvalues`` column contains relay-like strings will
   contribute discovered URLs.

Discovered URLs are inserted as validation candidates for the
[Validator][bigbrotr.services.validator.Validator] service via
[insert_relays_as_candidates][bigbrotr.services.common.queries.insert_relays_as_candidates].

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

    brotr = Brotr.from_yaml("config/brotr.yaml")
    finder = Finder.from_yaml("config/services/finder.yaml", brotr=brotr)

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
from bigbrotr.services.common.mixins import ConcurrentStreamMixin
from bigbrotr.services.common.queries import insert_relays_as_candidates
from bigbrotr.services.common.types import ApiCheckpoint, FinderCursor

from .configs import ApiSourceConfig, FinderConfig
from .queries import (
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_api_checkpoints,
    fetch_cursors_to_find,
    upsert_api_checkpoints,
    upsert_finder_cursors,
)
from .utils import extract_relays_from_tagvalues, fetch_api, stream_event_relays


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Finder(ConcurrentStreamMixin, BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the
    [Validator][bigbrotr.services.validator.Validator] service via
    [insert_relays_as_candidates][bigbrotr.services.common.queries.insert_relays_as_candidates].

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

        enabled = [s for s in self._config.api.sources if s.enabled]

        buffer: list[Relay] = []
        pending_checkpoints: list[ApiCheckpoint] = []

        self.set_gauge("total_sources", len(enabled))
        self.set_gauge("sources_fetched", 0)
        self.set_gauge("candidates_found_from_api", 0)

        self._logger.info("api_started", source_count=len(enabled))

        async for relays, checkpoint in self._find_from_api_worker(enabled):
            buffer.extend(relays)
            pending_checkpoints.append(checkpoint)
            self.inc_gauge("sources_fetched")

        if pending_checkpoints:
            await upsert_api_checkpoints(self._brotr, pending_checkpoints)

        found = await insert_relays_as_candidates(self._brotr, buffer)
        self.set_gauge("candidates_found_from_api", found)

        self._logger.info("api_completed", found=found, collected=len(buffer))
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
        now = int(time.time())

        async with aiohttp.ClientSession() as session:
            for i, source in enumerate(sources):
                if not self.is_running:
                    return

                cooldown = self._config.api.cooldown
                last_checked = checkpoint_map[source.url].timestamp
                if now - last_checked < cooldown:
                    self._logger.debug(
                        "api_skipped",
                        url=source.url,
                        seconds_left=cooldown - (now - last_checked),
                    )
                    continue

                try:
                    relays = await fetch_api(session, source, self._config.api.max_response_size)
                    self._logger.debug("api_fetched", url=source.url, count=len(relays))
                    yield relays, ApiCheckpoint(key=source.url, timestamp=int(time.time()))
                except (TimeoutError, OSError, aiohttp.ClientError, ValueError) as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

                if (
                    self._config.api.request_delay > 0
                    and i < len(sources) - 1
                    and await self.wait(self._config.api.request_delay)
                ):
                    return

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

        cursors = await fetch_cursors_to_find(self._brotr)
        if not cursors:
            self._logger.debug("no_relays_to_scan")
            return 0

        self._event_semaphore = asyncio.Semaphore(self._config.events.parallel_relays)
        self._phase_start = time.monotonic()

        total_found = 0
        buffer: list[Relay] = []
        pending_cursors: dict[str, FinderCursor] = {}
        batch_size = self._config.events.batch_size

        self.set_gauge("relays_seen", 0)
        self.set_gauge("rows_seen", 0)
        self.set_gauge("candidates_found_from_events", 0)

        self._logger.info("scan_started", relay_count=len(cursors))

        async for relays, cursor in self._iter_concurrent(cursors, self._find_from_events_worker):
            buffer.extend(relays)
            pending_cursors[cursor.key] = cursor
            self.inc_gauge("rows_seen")
            if len(buffer) >= batch_size:
                found = await insert_relays_as_candidates(self._brotr, buffer)
                total_found += found
                self.inc_gauge("candidates_found_from_events", found)
                buffer = []
                await upsert_finder_cursors(self._brotr, pending_cursors.values())
                pending_cursors = {}

        if buffer:
            found = await insert_relays_as_candidates(self._brotr, buffer)
            total_found += found
            self.inc_gauge("candidates_found_from_events", found)
        if pending_cursors:
            await upsert_finder_cursors(self._brotr, pending_cursors.values())

        self._logger.info("scan_completed", found=total_found)
        return total_found

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
        async with self._event_semaphore:
            if not self.is_running or (
                time.monotonic() - self._phase_start > self._config.events.max_duration
            ):
                return
            try:
                deadline = time.monotonic() + self._config.events.max_relay_time
                async for row in stream_event_relays(
                    self._brotr, cursor, self._config.events.scan_size
                ):
                    relays = extract_relays_from_tagvalues([row])
                    updated = FinderCursor(
                        key=cursor.key,
                        timestamp=row["seen_at"],
                        id=row["event_id"].hex(),
                    )
                    yield relays, updated
                    if time.monotonic() > deadline:
                        return
            except Exception as e:  # Worker exception boundary — protects TaskGroup
                self._logger.error(
                    "event_scan_worker_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    relay=cursor.key,
                )
            finally:
                self.inc_gauge("relays_seen")
