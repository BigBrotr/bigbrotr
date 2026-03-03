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
[insert_relays_as_candidates][bigbrotr.services.validator.queries.insert_relays_as_candidates].

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
from bigbrotr.services.common.types import EventRelayCursor
from bigbrotr.services.validator.queries import insert_relays_as_candidates
from bigbrotr.utils.http import read_bounded_json

from .configs import ApiSourceConfig, FinderConfig
from .queries import (
    delete_stale_api_checkpoints,
    delete_stale_cursors,
    fetch_event_relay_cursors,
    load_api_checkpoints,
    save_api_checkpoints,
    save_event_relay_cursor,
    scan_event_relay,
)
from .utils import extract_relays_from_response, extract_relays_from_tagvalues


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Finder(BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the
    [Validator][bigbrotr.services.validator.Validator] service via
    [insert_relays_as_candidates][bigbrotr.services.validator.queries.insert_relays_as_candidates].

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

        api_state = await load_api_checkpoints(self._brotr)
        now = int(time.time())

        seen: set[str] = set()
        all_relays: list[Relay] = []
        fetched_sources: list[str] = []

        async with aiohttp.ClientSession() as session:
            async for source, relays in self._iter_api_relays(session, api_state, now):
                for relay in relays:
                    if relay.url not in seen:
                        seen.add(relay.url)
                        all_relays.append(relay)
                api_state[source.url] = int(time.time())
                fetched_sources.append(source.url)

        if fetched_sources:
            checkpoints = {url: api_state[url] for url in fetched_sources}
            await save_api_checkpoints(self._brotr, checkpoints)

        found = await insert_relays_as_candidates(self._brotr, all_relays)

        self.set_gauge("api_candidates", found)
        self.inc_counter("total_api_candidates", found)
        self._logger.info("apis_completed", found=found, collected=len(all_relays))
        return found

    async def _iter_api_relays(
        self,
        session: aiohttp.ClientSession,
        api_state: dict[str, int],
        now: int,
    ) -> AsyncIterator[tuple[ApiSourceConfig, list[Relay]]]:
        """Yield (source, relays) for each enabled API source that is due for refresh."""
        enabled = [s for s in self._config.api.sources if s.enabled]
        for i, source in enumerate(enabled):
            if not self.is_running:
                return

            last_checked = api_state.get(source.url, 0)
            if now - last_checked < source.interval:
                self._logger.debug(
                    "api_skipped",
                    url=source.url,
                    seconds_left=source.interval - (now - last_checked),
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

        Cleans up stale cursors, fetches current cursor positions, scans
        all relays concurrently (bounded by ``events.parallel_relays``),
        and emits discovery metrics.

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
        found, events, scanned, failures = await self._run_event_scans(cursors)

        self.set_gauge("event_candidates", found)
        self.set_gauge("relays_scanned", scanned)
        self.inc_counter("total_event_candidates", found)
        self.inc_counter("total_events_processed", events)
        self.inc_counter("total_scan_failures", failures)

        self._logger.info(
            "events_completed",
            found=found,
            events_scanned=events,
            relays_scanned=scanned,
            scan_failures=failures,
        )
        return found

    async def _run_event_scans(self, cursors: list[EventRelayCursor]) -> tuple[int, int, int, int]:
        """Scan all relays concurrently and aggregate results.

        Returns:
            Tuple of (candidates_found, events_scanned, relays_scanned,
            scan_failures).
        """
        semaphore = asyncio.Semaphore(self._config.events.parallel_relays)
        phase_start = time.monotonic()
        max_duration = self._config.events.max_duration

        async def _bounded_scan(cursor: EventRelayCursor) -> tuple[int, int] | None:
            async with semaphore:
                if not self.is_running:
                    return None
                if time.monotonic() - phase_start > max_duration:
                    return None
                return await self._scan_relay_events(cursor)

        tasks: list[asyncio.Task[tuple[int, int] | None]] = []
        try:
            async with asyncio.TaskGroup() as tg:
                tasks.extend(tg.create_task(_bounded_scan(c)) for c in cursors)
        except ExceptionGroup:
            pass  # Individual errors are logged in the task loop below

        total_found = 0
        total_events = 0
        relays_scanned = 0
        scan_failures = 0

        for task in tasks:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                self._logger.error(
                    "event_scan_worker_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                scan_failures += 1
                continue
            result = task.result()
            if result is None:
                continue
            events, found = result
            total_events += events
            total_found += found
            relays_scanned += 1

        return total_found, total_events, relays_scanned, scan_failures

    async def _scan_relay_events(self, cursor: EventRelayCursor) -> tuple[int, int]:
        """Scan events from a single relay using composite cursor pagination.

        Args:
            cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
                with relay URL and pagination position.

        Returns:
            Tuple of (events_scanned, candidates_found).
        """
        events_scanned = 0
        candidates_found = 0
        relay_url = cursor.relay_url
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
            cursor = EventRelayCursor(
                relay_url=relay_url,
                seen_at=last_row["seen_at"],
                event_id=last_row["event_id"],
            )

            if relays:
                try:
                    candidates_found += await insert_relays_as_candidates(self._brotr, relays)
                except (asyncpg.PostgresError, OSError) as e:
                    self._logger.error(
                        "insert_candidates_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(relays),
                    )
                    break

            try:
                await save_event_relay_cursor(self._brotr, cursor)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "cursor_update_failed",
                    relay=relay_url,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                break
            events_scanned += len(rows)

            if len(rows) < self._config.events.batch_size:
                break

        return events_scanned, candidates_found
