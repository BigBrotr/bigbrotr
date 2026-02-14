"""Finder service for BigBrotr.

Discovers Nostr relay URLs from two sources:

1. **External APIs** -- Public endpoints like nostr.watch that list relays.
2. **Database events** -- Relay URLs extracted from stored Nostr events:
   - Kind 3 (NIP-02): ``content`` is JSON with relay URLs as keys.
   - Kind 10002 (NIP-65): ``r`` tags contain relay URLs.
   - Kind 2 (deprecated, opt-in): ``content`` field contains a relay URL.
   - Any event with ``r`` tags.

Discovered URLs are inserted as validation candidates for the
[Validator][bigbrotr.services.validator.Validator] service via
[upsert_candidates][bigbrotr.services.common.queries.upsert_candidates].

Note:
    Event scanning uses per-relay cursor-based pagination so that
    historical events inserted by the
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] are
    eventually processed. Cursors are stored as
    [ServiceState][bigbrotr.models.service_state.ServiceState] records
    with ``state_type='cursor'`` and ``state_value.last_seen_at``.

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

import json
import time
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp
import asyncpg
from nostr_sdk import NostrSdkError, RelayUrl
from pydantic import BaseModel, Field

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .common.queries import get_all_relay_urls, get_events_with_relay_urls, upsert_candidates


if TYPE_CHECKING:
    import ssl

    from bigbrotr.core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class FinderConcurrencyConfig(BaseModel):
    """Concurrency limits for parallel API requests.

    See Also:
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    max_parallel: int = Field(default=5, ge=1, le=20, description="Maximum concurrent API requests")


class EventsConfig(BaseModel):
    """Event scanning configuration for discovering relay URLs from stored events.

    Requires a full database schema with ``tags``, ``tagvalues``, and ``content``
    columns. Set ``enabled=false`` for minimal-schema implementations (e.g., LilBrotr).

    See Also:
        [get_events_with_relay_urls][bigbrotr.services.common.queries.get_events_with_relay_urls]:
            The SQL query driven by ``batch_size`` and ``kinds``.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(
        default=True,
        description="Enable event scanning (requires full schema with tags/content columns)",
    )
    batch_size: int = Field(
        default=1000, ge=100, le=10_000, description="Events to process per batch"
    )
    kinds: list[int] = Field(
        default_factory=lambda: [int(EventKind.CONTACTS), int(EventKind.RELAY_LIST)],
        description="Event kinds to scan (3=contacts, 10002=relay list)",
    )


class ApiSourceConfig(BaseModel):
    """Single API source configuration."""

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=0.1, le=120.0, description="Request timeout")
    connect_timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="HTTP connection timeout (capped to total timeout)",
    )


class ApiConfig(BaseModel):
    """API fetching configuration -- discovers relay URLs from public APIs.

    See Also:
        [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig]:
            Per-source URL, timeout, and enablement settings.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable API fetching")
    sources: list[ApiSourceConfig] = Field(
        default_factory=lambda: [
            ApiSourceConfig(url="https://api.nostr.watch/v1/online"),
            ApiSourceConfig(url="https://api.nostr.watch/v1/offline"),
        ]
    )
    delay_between_requests: float = Field(
        default=1.0, ge=0.0, le=10.0, description="Delay between API requests"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify TLS certificates (disable only for testing/internal APIs)",
    )


class FinderConfig(BaseServiceConfig):
    """Finder service configuration.

    See Also:
        [Finder][bigbrotr.services.finder.Finder]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``log_level`` fields.
    """

    concurrency: FinderConcurrencyConfig = Field(default_factory=FinderConcurrencyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


# =============================================================================
# Service
# =============================================================================


class Finder(BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the
    [Validator][bigbrotr.services.validator.Validator] service via
    [upsert_candidates][bigbrotr.services.common.queries.upsert_candidates].

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
        self._found_relays: int = 0

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute a single discovery cycle across all configured sources.

        Scans stored events and fetches external APIs (in that order) to
        discover relay URLs. Use ``run_forever()`` for continuous operation.
        """
        cycle_start = time.monotonic()
        self._found_relays = 0

        # Discover relay URLs from event scanning
        if self._config.events.enabled:
            await self._find_from_events()

        # Discover relay URLs from APIs
        if self._config.api.enabled:
            await self._find_from_api()

        elapsed = time.monotonic() - cycle_start
        self._logger.info("cycle_completed", found=self._found_relays, duration_s=round(elapsed, 2))

    async def _find_from_events(self) -> None:
        """Discover relay URLs from stored events using per-relay cursor pagination.

        Iterates over all relays in the database and scans their associated events
        for relay URLs embedded in tags and content fields. Each relay maintains
        its own cursor (based on ``seen_at`` timestamp) so that historical events
        inserted by the Synchronizer are still processed.
        """
        total_events_scanned = 0
        total_relays_found = 0
        relays_processed = 0

        # Fetch all relays from database
        try:
            relay_urls = await get_all_relay_urls(self._brotr)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning("fetch_relays_failed", error=str(e), error_type=type(e).__name__)
            return

        if not relay_urls:
            self._logger.debug("no_relays_to_scan")
            return

        self._logger.debug("events_scan_started", relay_count=len(relay_urls))

        # Fetch all cursors in a single query to avoid N+1 per-relay lookups
        try:
            cursors = await self._fetch_all_cursors()
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.warning("fetch_cursors_failed", error=str(e), error_type=type(e).__name__)
            return

        for relay_url in relay_urls:
            if not self.is_running:
                break

            relay_events, relay_relays = await self._scan_relay_events(relay_url, cursors)
            total_events_scanned += relay_events
            total_relays_found += relay_relays
            relays_processed += 1

        self._found_relays += total_relays_found
        self._logger.info(
            "events_completed",
            scanned=total_events_scanned,
            relays_found=total_relays_found,
            relays_processed=relays_processed,
        )

    async def _fetch_all_cursors(self) -> dict[str, int]:
        """Fetch all event-scanning cursors in a single query."""
        results = await self._brotr.get_service_state(self.SERVICE_NAME, ServiceStateType.CURSOR)
        return {r.state_key: r.state_value.get("last_seen_at", 0) for r in results}

    async def _scan_relay_events(self, relay_url: str, cursors: dict[str, int]) -> tuple[int, int]:
        """
        Scan events from a single relay using cursor-based pagination.

        Args:
            relay_url: The relay URL to scan events from
            cursors: Pre-fetched mapping of relay URL to last_seen_at timestamp

        Returns:
            Tuple of (events_scanned, relays_found)
        """
        events_scanned = 0
        relays_found = 0

        # Look up cursor from pre-fetched cache (avoids per-relay query)
        last_seen_at = cursors.get(relay_url, 0)

        while self.is_running:
            try:
                rows = await get_events_with_relay_urls(
                    self._brotr,
                    relay_url,
                    last_seen_at,
                    self._config.events.kinds,
                    self._config.events.batch_size,
                )
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

            relays = self._extract_relays_from_rows(rows)
            chunk_events = len(rows)
            last_seen_at_update = rows[-1]["seen_at"]

            relays_found += await self._persist_scan_chunk(relay_url, relays, last_seen_at_update)
            events_scanned += chunk_events
            last_seen_at = last_seen_at_update

            # Stop if chunk wasn't full
            if chunk_events < self._config.events.batch_size:
                break

        return events_scanned, relays_found

    def _extract_relays_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Relay]:
        """Extract and deduplicate relay URLs from event rows.

        Parses relay URLs from three sources within each event row:

        - ``r`` tags: any event with ``["r", "<url>"]`` tag entries.
        - Kind 2 content: the deprecated NIP-01 recommend-relay event.
        - Kind 3 content: NIP-02 contact list with JSON relay map as keys.

        Args:
            rows: Event rows with ``kind``, ``tags``, ``content``,
                and ``seen_at`` keys (from
                ``get_events_with_relay_urls``).

        Returns:
            Mapping of normalized relay URL to
            [Relay][bigbrotr.models.relay.Relay] for deduplication.
        """
        relays: dict[str, Relay] = {}

        for row in rows:
            kind = row["kind"]
            tags = row["tags"]
            content = row["content"]

            # Extract relay URLs from tags (r-tags)
            if tags:
                for tag in tags:
                    if isinstance(tag, list) and len(tag) >= 2 and tag[0] == "r":  # noqa: PLR2004
                        validated = self._validate_relay_url(tag[1])
                        if validated:
                            relays[validated.url] = validated

            # Kind 2: content is the relay URL (deprecated NIP)
            if kind == EventKind.RECOMMEND_RELAY and content:
                validated = self._validate_relay_url(content.strip())
                if validated:
                    relays[validated.url] = validated

            # Kind 3: content may be JSON with relay URLs as keys
            if kind == EventKind.CONTACTS and content:
                try:
                    relay_data = json.loads(content)
                    if isinstance(relay_data, dict):
                        for url in relay_data:
                            validated = self._validate_relay_url(url)
                            if validated:
                                relays[validated.url] = validated
                except (json.JSONDecodeError, TypeError):
                    pass

        return relays

    async def _persist_scan_chunk(
        self, relay_url: str, relays: dict[str, Relay], last_seen_at: int
    ) -> int:
        """Upsert discovered relay candidates and save the scan cursor.

        Args:
            relay_url: Source relay whose events were scanned.
            relays: Deduplicated mapping of relay URL to
                [Relay][bigbrotr.models.relay.Relay].
            last_seen_at: Timestamp of the last event in the chunk (cursor
                value persisted as a
                [ServiceState][bigbrotr.models.service_state.ServiceState]
                record).

        Returns:
            Number of relays successfully upserted.
        """
        found = 0

        # Insert discovered relays as candidates
        if relays:
            try:
                found = await upsert_candidates(self._brotr, relays.values())
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "insert_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(relays),
                )

        # Update cursor for this relay
        await self._brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.CURSOR,
                    state_key=relay_url,
                    state_value={"last_seen_at": last_seen_at},
                    updated_at=int(time.time()),
                )
            ]
        )

        return found

    def _validate_relay_url(self, url: str) -> Relay | None:
        """Validate and normalize a relay URL.

        Delegates to the [Relay][bigbrotr.models.relay.Relay] constructor
        which performs RFC 3986 validation and network detection.

        Args:
            url: Potential relay URL string.

        Returns:
            [Relay][bigbrotr.models.relay.Relay] object if valid,
            ``None`` otherwise.
        """
        if not url or not isinstance(url, str):
            return None

        url = url.strip()
        if not url:
            return None

        try:
            return Relay(url)
        except (ValueError, TypeError):
            return None

    async def _find_from_api(self) -> None:
        """Discover relay URLs from configured external API endpoints.

        Fetches each enabled [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig]
        sequentially (with a configurable delay between requests),
        deduplicates the results, and inserts discovered URLs as
        validation candidates via
        [upsert_candidates][bigbrotr.services.common.queries.upsert_candidates].
        """
        relays: dict[str, Relay] = {}  # url -> Relay for deduplication
        sources_checked = 0

        # SSL context: True uses system CA bundle, False disables verification
        ssl_context: ssl.SSLContext | bool = True
        if not self._config.api.verify_ssl:
            ssl_context = False
            self._logger.warning("ssl_verification_disabled")

        connector = aiohttp.TCPConnector(ssl=ssl_context)

        # Reuse a single session for connection pooling across all API requests
        async with aiohttp.ClientSession(connector=connector) as session:
            enabled_sources = [s for s in self._config.api.sources if s.enabled]
            for i, source in enumerate(enabled_sources):
                if not self.is_running:
                    self._logger.info("api_discovery_interrupted", reason="shutdown")
                    break

                try:
                    source_relays = await self._fetch_single_api(session, source)
                    for relay_url in source_relays:
                        validated = self._validate_relay_url(str(relay_url))
                        if validated:
                            relays[validated.url] = validated
                    sources_checked += 1

                    self._logger.debug("api_fetched", url=source.url, count=len(source_relays))

                    # Rate-limit between API requests (skip delay after the last source)
                    if (
                        self._config.api.delay_between_requests > 0
                        and i < len(enabled_sources) - 1
                        and await self.wait(self._config.api.delay_between_requests)
                    ):
                        break

                except (TimeoutError, OSError, aiohttp.ClientError) as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

        # Insert as validation candidates (service_name='validator')
        if relays:
            try:
                self._found_relays += await upsert_candidates(self._brotr, relays.values())
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error(
                    "insert_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(relays),
                )

        if sources_checked > 0:
            self._logger.info("apis_completed", sources=sources_checked, relays=len(relays))

    async def _fetch_single_api(
        self, session: aiohttp.ClientSession, source: ApiSourceConfig
    ) -> list[RelayUrl]:
        """Fetch relay URLs from a single API endpoint.

        Expects the API to return a JSON array of relay URL strings.

        Args:
            session: Shared aiohttp ClientSession for connection pooling.
            source: API source configuration (URL, timeout, enabled).

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
            data = await resp.json()

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        try:
                            relay_url = RelayUrl.parse(item)
                            relays.append(relay_url)
                        except NostrSdkError:
                            self._logger.debug("invalid_relay_url", url=item)
                    else:
                        self._logger.debug("unexpected_item_type", url=source.url, item=item)
            else:
                self._logger.debug("unexpected_api_response", url=source.url, data=data)

        return relays
