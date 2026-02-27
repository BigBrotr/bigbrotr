"""Finder service for BigBrotr.

Discovers Nostr relay URLs from two sources:

1. **External APIs** -- Public endpoints like nostr.watch that list relays.
   Each API source declares how relay URLs are extracted from its JSON
   response (flat array, nested path, object keys, etc.) via
   [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig].
2. **Database events** -- Tag values from all stored events are parsed via
   [parse_relay_url][bigbrotr.services.common.utils.parse_relay_url]; only
   valid ``wss://`` / ``ws://`` URLs pass validation. This is kind-agnostic:
   any event whose ``tagvalues`` column contains relay-like strings will
   contribute discovered URLs.

Discovered URLs are inserted as validation candidates for the
[Validator][bigbrotr.services.validator.Validator] service via
[insert_candidates][bigbrotr.services.common.queries.insert_candidates].

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
from nostr_sdk import NostrSdkError, RelayUrl

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.queries import (
    delete_orphan_cursors,
    fetch_all_relays,
    get_all_cursor_values,
    insert_candidates,
    scan_event_relay,
)
from bigbrotr.services.common.types import EventRelayCursor
from bigbrotr.services.common.utils import parse_relay_url
from bigbrotr.utils.http import read_bounded_json

from .configs import ApiSourceConfig, FinderConfig
from .utils import extract_relays_from_rows, extract_urls_from_response


if TYPE_CHECKING:
    import ssl
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Finder(BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the
    [Validator][bigbrotr.services.validator.Validator] service via
    [insert_candidates][bigbrotr.services.common.queries.insert_candidates].

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
        """Execute a single discovery cycle across all configured sources.

        Orchestrates discovery and cycle-level logging. Delegates the core
        work to ``find``.
        """
        self._logger.info(
            "cycle_started",
            events_enabled=self._config.events.enabled,
            api_enabled=self._config.api.enabled,
        )
        found = await self.find()
        self._logger.info("cycle_completed", found=found)

    async def find(self) -> int:
        """Discover relay URLs from all configured sources.

        Runs event scanning and API fetching (in that order), respecting
        the ``events.enabled`` and ``api.enabled`` configuration flags.
        Returns the total number of relay URLs inserted as candidates.

        This is the method ``run()`` delegates to. It can also be called
        standalone without cycle-level logging.

        Returns:
            Total number of relay URLs discovered and inserted.
        """
        found = 0
        found += await self.find_from_events()
        found += await self.find_from_api()
        return found

    async def find_from_events(self) -> int:
        """Discover relay URLs from stored events using per-relay cursor pagination.

        Scans all relays in the database concurrently (bounded by
        ``concurrency.max_parallel_events``) for relay URLs embedded in tags
        and content fields. Each relay maintains its own cursor (based on
        ``seen_at`` timestamp) so that historical events inserted by the
        Synchronizer are still processed.

        Uses ``asyncio.TaskGroup`` with a semaphore to bound concurrent
        database queries, following the same pattern as
        [Synchronizer._sync_all_relays][bigbrotr.services.synchronizer.Synchronizer].

        Controlled by ``events.enabled`` in
        [FinderConfig][bigbrotr.services.finder.FinderConfig].

        Returns:
            Number of relay URLs discovered and inserted as candidates.
        """
        if not self._config.events.enabled:
            return 0

        total_events_scanned = 0
        total_relays_found = 0
        relays_processed = 0
        relays_failed = 0

        try:
            removed = await delete_orphan_cursors(self._brotr, self.SERVICE_NAME)
            if removed:
                self._logger.info("orphan_cursors_removed", count=removed)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning(
                "orphan_cursor_cleanup_failed", error=str(e), error_type=type(e).__name__
            )

        try:
            all_relays = await fetch_all_relays(self._brotr)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning("fetch_relays_failed", error=str(e), error_type=type(e).__name__)
            return 0

        relay_urls = [r.url for r in all_relays]
        if not relay_urls:
            self._logger.debug("no_relays_to_scan")
            return 0

        self._logger.debug("events_scan_started", relay_count=len(relay_urls))

        try:
            cursors = await self._fetch_all_cursors()
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning("fetch_cursors_failed", error=str(e), error_type=type(e).__name__)
            return 0

        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel_events)

        async def _bounded_scan(url: str) -> tuple[int, int]:
            async with semaphore:
                if not self.is_running:
                    return 0, 0
                return await self._scan_relay_events(url, cursors)

        tasks: list[asyncio.Task[tuple[int, int]]] = []
        try:
            async with asyncio.TaskGroup() as tg:
                tasks.extend(tg.create_task(_bounded_scan(relay_url)) for relay_url in relay_urls)
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                self._logger.error(
                    "event_scan_worker_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        for task in tasks:
            if task.cancelled():
                continue
            if task.exception() is None:
                events, relays = task.result()
                total_events_scanned += events
                total_relays_found += relays
                relays_processed += 1
            else:
                relays_failed += 1

        self.set_gauge("events_scanned", total_events_scanned)
        self.set_gauge("relays_found", total_relays_found)
        self.set_gauge("relays_processed", relays_processed)
        self.set_gauge("relays_failed", relays_failed)
        self.inc_counter("total_events_scanned", total_events_scanned)
        self.inc_counter("total_relays_found", total_relays_found)

        self._logger.info(
            "events_completed",
            scanned=total_events_scanned,
            relays_found=total_relays_found,
            relays_processed=relays_processed,
            relays_failed=relays_failed,
        )
        return total_relays_found

    async def discover_from_apis(self) -> AsyncIterator[tuple[str, dict[str, Relay]]]:
        """Yield ``(source_url, discovered_relays)`` from each enabled API source.

        Each yield produces the validated relay dict from one API endpoint.
        Connection pooling is managed internally via a shared aiohttp session.
        The generator handles rate limiting between sources.

        Yields:
            Tuple of (source URL, dict mapping relay URL to Relay object).
        """
        ssl_context: ssl.SSLContext | bool = True
        if not self._config.api.verify_ssl:
            ssl_context = False

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            enabled = [s for s in self._config.api.sources if s.enabled]
            for i, source in enumerate(enabled):
                if not self.is_running:
                    break
                try:
                    source_relays = await self._fetch_single_api(session, source)
                    validated: dict[str, Relay] = {}
                    for relay_url in source_relays:
                        r = parse_relay_url(str(relay_url))
                        if r:
                            validated[r.url] = r
                    yield source.url, validated

                    # Rate-limit (skip after last)
                    if (
                        self._config.api.delay_between_requests > 0
                        and i < len(enabled) - 1
                        and await self.wait(self._config.api.delay_between_requests)
                    ):
                        break
                except (TimeoutError, OSError, aiohttp.ClientError, ValueError) as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

    async def find_from_api(self) -> int:
        """Discover relay URLs from configured external API endpoints.

        Fetches each enabled API source via ``discover_from_apis``,
        deduplicates the results, and inserts discovered URLs as validation
        candidates.

        Controlled by ``api.enabled`` in
        [FinderConfig][bigbrotr.services.finder.FinderConfig].

        Returns:
            Number of relay URLs inserted as candidates.
        """
        if not self._config.api.enabled:
            return 0

        found = 0
        all_relays: dict[str, Relay] = {}
        async for source_url, relays in self.discover_from_apis():
            all_relays.update(relays)
            self._logger.debug("api_fetched", url=source_url, count=len(relays))

        if all_relays:
            try:
                found = await insert_candidates(self._brotr, list(all_relays.values()))
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "insert_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(all_relays),
                )

        self.set_gauge("api_relays", len(all_relays))
        self.inc_counter("total_api_relays_found", len(all_relays))

        self._logger.info("apis_completed", found=found, fetched=len(all_relays))
        return found

    async def _fetch_all_cursors(self) -> dict[str, EventRelayCursor]:
        """Fetch all event-scanning cursors in a single query.

        Returns a dict mapping relay URL to
        [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor].
        Cursor rows with missing or incomplete fields (e.g. legacy
        ``last_seen_at``-only records) are omitted -- their relay will
        be rescanned from the beginning, which is safe because
        ``insert_candidates`` is idempotent.
        """
        raw = await get_all_cursor_values(self._brotr, self.SERVICE_NAME)
        cursors: dict[str, EventRelayCursor] = {}
        for relay_url, value in raw.items():
            seen_at = value.get("seen_at")
            event_id_hex = value.get("event_id")
            if seen_at is not None and event_id_hex is not None:
                try:
                    cursors[relay_url] = EventRelayCursor(
                        relay_url=relay_url,
                        seen_at=int(seen_at),
                        event_id=bytes.fromhex(str(event_id_hex)),
                    )
                except (ValueError, TypeError):
                    self._logger.warning(
                        "invalid_cursor_data",
                        relay=relay_url,
                        seen_at=seen_at,
                        event_id=event_id_hex,
                    )
        return cursors

    async def _scan_relay_events(
        self, relay_url: str, cursors: dict[str, EventRelayCursor]
    ) -> tuple[int, int]:
        """Scan events from a single relay using composite cursor pagination.

        Args:
            relay_url: The relay URL to scan events from.
            cursors: Pre-fetched mapping of relay URL to
                [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor].

        Returns:
            Tuple of (events_scanned, relays_found).
        """
        events_scanned = 0
        relays_found = 0
        cursor = cursors.get(relay_url, EventRelayCursor(relay_url=relay_url))

        while self.is_running:
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

            relays = extract_relays_from_rows(rows)
            chunk_events = len(rows)
            last_row = rows[-1]
            cursor = EventRelayCursor(
                relay_url=relay_url,
                seen_at=last_row["seen_at"],
                event_id=last_row["event_id"],
            )

            relays_found += await self._persist_scan_chunk(relays, cursor)
            events_scanned += chunk_events

            if chunk_events < self._config.events.batch_size:
                break

        return events_scanned, relays_found

    async def _persist_scan_chunk(self, relays: dict[str, Relay], cursor: EventRelayCursor) -> int:
        """Upsert discovered relay candidates and save the scan cursor."""
        found = 0

        if relays:
            try:
                found = await insert_candidates(self._brotr, list(relays.values()))
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "insert_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(relays),
                )

        seen_at = cursor.seen_at
        event_id = cursor.event_id
        if seen_at is None or event_id is None:
            msg = "cursor must have seen_at and event_id set"
            raise ValueError(msg)
        try:
            await self._brotr.upsert_service_state(
                [
                    ServiceState(
                        service_name=self.SERVICE_NAME,
                        state_type=ServiceStateType.CURSOR,
                        state_key=cursor.relay_url,
                        state_value={
                            "seen_at": seen_at,
                            "event_id": event_id.hex(),
                        },
                        updated_at=int(time.time()),
                    )
                ]
            )
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.error(
                "cursor_update_failed",
                relay=cursor.relay_url,
                error=str(e),
                error_type=type(e).__name__,
            )

        return found

    async def _fetch_single_api(
        self, session: aiohttp.ClientSession, source: ApiSourceConfig
    ) -> list[RelayUrl]:
        """Fetch relay URLs from a single API endpoint.

        The response format is configurable per source via the ``jmespath``
        field on [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig].
        When left at its default (``[*]``) the response is expected to be a
        flat JSON array of URL strings.

        Args:
            session: Shared aiohttp ClientSession for connection pooling.
            source: API source configuration (URL, timeout, extraction params).

        Returns:
            List of parsed RelayUrl objects from the API response.
        """
        relays: list[RelayUrl] = []

        timeout = aiohttp.ClientTimeout(
            total=source.timeout,
            connect=min(source.connect_timeout, source.timeout),
            sock_read=source.timeout,
        )
        async with session.get(source.url, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await read_bounded_json(resp, self._config.api.max_response_size)

            url_strings = extract_urls_from_response(data, source.jmespath)

            for item in url_strings:
                try:
                    relays.append(RelayUrl.parse(item))
                except NostrSdkError:
                    self._logger.debug("invalid_relay_url", url=item)

        return relays
