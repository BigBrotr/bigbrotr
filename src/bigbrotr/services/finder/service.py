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
    with ``state_type='cursor'`` and a composite ``(seen_at, event_id)``
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
import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.mixins import ConcurrentStreamMixin
from bigbrotr.services.common.queries import insert_relays_as_candidates
from bigbrotr.services.common.types import ApiCheckpoint, FinderCursor
from bigbrotr.utils.http import read_bounded_json

from .configs import ApiSourceConfig, FinderConfig
from .queries import (
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_event_relay_cursors,
    load_api_checkpoints,
    save_api_checkpoints,
    save_event_relay_cursors,
    scan_event_relay,
)
from .utils import extract_relays_from_response, extract_relays_from_tagvalues


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

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

        Loads per-source timestamps from individual checkpoint records
        (one per API source URL), skips sources whose ``interval`` has
        not elapsed, fetches the rest sequentially, deduplicates across
        sources, and inserts discovered URLs as validation candidates.

        Returns:
            Number of relay URLs inserted as candidates.
        """
        if not self._config.api.enabled:
            return 0

        source_urls = [s.url for s in self._config.api.sources]
        loaded = await load_api_checkpoints(self._brotr, source_urls)
        api_state = {cp.key: cp for cp in loaded}
        now = int(time.time())

        seen: set[str] = set()
        all_relays: list[Relay] = []
        updated: list[ApiCheckpoint] = []

        async with aiohttp.ClientSession() as session:
            async for source, relays in self._iter_api_relays(session, api_state, now):
                for relay in relays:
                    if relay.url not in seen:
                        seen.add(relay.url)
                        all_relays.append(relay)
                updated.append(ApiCheckpoint(key=source.url, timestamp=int(time.time())))

        if updated:
            await save_api_checkpoints(self._brotr, updated)

        found = await insert_relays_as_candidates(self._brotr, all_relays)

        self.set_gauge("api_candidates", found)
        self.inc_counter("total_api_candidates", found)
        self._logger.info("apis_completed", found=found, collected=len(all_relays))
        return found

    async def _iter_api_relays(
        self,
        session: aiohttp.ClientSession,
        api_state: dict[str, ApiCheckpoint],
        now: int,
    ) -> AsyncIterator[tuple[ApiSourceConfig, list[Relay]]]:
        """Yield (source, relays) for each enabled API source that is due for refresh."""
        enabled = [s for s in self._config.api.sources if s.enabled]
        for i, source in enumerate(enabled):
            if not self.is_running:
                return

            checkpoint = api_state.get(source.url)
            last_checked = checkpoint.timestamp if checkpoint else 0
            cooldown = self._config.api.cooldown
            if now - last_checked < cooldown:
                self._logger.debug(
                    "api_skipped",
                    url=source.url,
                    seconds_left=cooldown - (now - last_checked),
                )
                continue

            try:
                relays = await self._fetch_single_api(session, source)
                self._logger.debug("api_fetched", url=source.url, count=len(relays))
                yield source, relays
            except (TimeoutError, OSError, aiohttp.ClientError, ValueError) as e:
                self._logger.warning(
                    "api_fetch_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    url=source.url,
                )

            if (
                self._config.api.request_delay > 0
                and i < len(enabled) - 1
                and await self.wait(self._config.api.request_delay)
            ):
                return

    async def _fetch_single_api(
        self, session: aiohttp.ClientSession, source: ApiSourceConfig
    ) -> list[Relay]:
        """Fetch and validate relay URLs from a single API endpoint.

        The response format is configurable per source via the ``expression``
        field on [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig].
        When left at its default (``[*]``) the response is expected to be a
        flat JSON array of URL strings.

        Args:
            session: Shared aiohttp ClientSession for connection pooling.
            source: API source configuration (URL, timeout, extraction params).

        Returns:
            Deduplicated list of Relay objects.
        """
        timeout = aiohttp.ClientTimeout(
            total=source.timeout,
            connect=min(source.connect_timeout, source.timeout),
            sock_read=source.timeout,
        )
        async with session.get(source.url, timeout=timeout, ssl=not source.allow_insecure) as resp:
            resp.raise_for_status()
            data = await read_bounded_json(resp, self._config.api.max_response_size)
            return extract_relays_from_response(data, source.expression)

    # ── Event discovery ────────────────────────────────────────────

    async def find_from_events(self) -> int:
        """Discover relay URLs from stored events using cursor pagination.

        Fetches current cursor positions, scans all relays concurrently
        (bounded by ``events.parallel_relays``) via ``_iter_concurrent()``.
        Workers yield individual relay URLs. The parent accumulates them in a
        global buffer flushed at ``brotr.config.batch.max_size`` and saves
        cursors in batch after each flush.

        Returns:
            Number of relay URLs discovered and inserted as candidates.
        """
        if not self._config.events.enabled:
            return 0

        try:
            cursors = await fetch_event_relay_cursors(self._brotr)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning("fetch_cursors_failed", error=str(e), error_type=type(e).__name__)
            return 0
        if not cursors:
            self._logger.debug("no_relays_to_scan")
            return 0

        self._logger.debug("events_scan_started", relay_count=len(cursors))

        self.set_gauge("relays_total", len(cursors))
        self.set_gauge("relays_scanned", 0)
        self.set_gauge("event_candidates", 0)

        self._event_semaphore = asyncio.Semaphore(self._config.events.parallel_relays)
        self._phase_start = time.monotonic()

        total_found = 0
        relays_seen: set[str] = set()
        buffer: list[Relay] = []
        pending_cursors: dict[str, FinderCursor] = {}
        batch_size = self._brotr.config.batch.max_size

        async for relay, cursor in self._iter_concurrent(cursors, self._event_scan_worker):
            relays_seen.add(cursor.key)
            buffer.append(relay)
            pending_cursors[cursor.key] = cursor
            if len(buffer) >= batch_size:
                total_found += await self._flush_event_buffer(buffer, pending_cursors)
                self.set_gauge("relays_scanned", len(relays_seen))
                self.set_gauge("event_candidates", total_found)

        total_found += await self._flush_event_buffer(buffer, pending_cursors)
        self.set_gauge("relays_scanned", len(relays_seen))
        self.set_gauge("event_candidates", total_found)

        self._logger.info(
            "events_completed",
            found=total_found,
            relays_scanned=len(relays_seen),
        )
        return total_found

    async def _event_scan_worker(
        self, cursor: FinderCursor
    ) -> AsyncGenerator[tuple[Relay, FinderCursor], None]:
        """Stream relay URLs from a single relay's events for ``_iter_concurrent``.

        Acquires the per-phase semaphore, checks phase duration, and delegates
        to ``_stream_relay_batches``. On unexpected exception, logs and returns
        (yields nothing — the relay is silently skipped).
        """
        async with self._event_semaphore:
            if not self.is_running or (
                time.monotonic() - self._phase_start > self._config.events.max_duration
            ):
                return
            try:
                async for item in self._stream_relay_batches(cursor):
                    yield item
            except Exception as e:  # Worker exception boundary — protects TaskGroup
                self._logger.error(
                    "event_scan_worker_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    relay=cursor.key,
                )

    async def _flush_event_buffer(
        self,
        buffer: list[Relay],
        pending_cursors: dict[str, FinderCursor],
    ) -> int:
        """Flush the relay buffer and persist pending cursors.

        Args:
            buffer: Accumulated relay candidates (cleared after flush).
            pending_cursors: Per-relay cursor positions (cleared after flush).

        Returns:
            Number of candidates inserted.
        """
        inserted = 0
        if buffer:
            try:
                inserted = await insert_relays_as_candidates(self._brotr, list(buffer))
                self.inc_counter("total_event_candidates", inserted)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "insert_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(buffer),
                )
            buffer.clear()
        if pending_cursors:
            try:
                await save_event_relay_cursors(self._brotr, list(pending_cursors.values()))
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "cursor_update_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
            pending_cursors.clear()
        return inserted

    async def _stream_relay_batches(
        self, cursor: FinderCursor
    ) -> AsyncGenerator[tuple[Relay, FinderCursor], None]:
        """Stream relay URLs from a single relay using composite cursor pagination.

        Yields ``(relay, updated_cursor)`` for each discovered relay URL.
        The caller is responsible for buffering and persisting candidates and cursors.

        Args:
            cursor: [FinderCursor][bigbrotr.services.common.types.FinderCursor]
                with relay URL and pagination position.
        """
        relay_url = cursor.key
        scan_start = time.monotonic()
        max_relay_time = self._config.events.max_relay_time

        while self.is_running:
            if max_relay_time and time.monotonic() - scan_start > max_relay_time:
                break

            try:
                rows = await scan_event_relay(self._brotr, cursor, self._config.events.batch_size)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.warning(
                    "relay_event_query_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    relay=relay_url,
                )
                break

            if not rows:
                break

            relays = extract_relays_from_tagvalues(rows)
            last_row = rows[-1]
            cursor = FinderCursor(
                key=relay_url,
                timestamp=last_row["seen_at"],
                id=last_row["event_id"].hex(),
            )

            for relay in relays:
                yield relay, cursor

            if len(rows) < self._config.events.batch_size:
                break
