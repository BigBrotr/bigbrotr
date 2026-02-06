"""Finder service for BigBrotr.

Discovers Nostr relay URLs from two sources:

1. **External APIs** -- Public endpoints like nostr.watch that list relays.
2. **Database events** -- Relay URLs extracted from stored Nostr events:
   - Kind 2 (deprecated): ``content`` field contains a relay URL.
   - Kind 3 (NIP-02): ``content`` is JSON with relay URLs as keys.
   - Kind 10002 (NIP-65): ``r`` tags contain relay URLs.
   - Any event with ``r`` tags.

Discovered URLs are inserted as validation candidates for the Validator service.

Usage::

    from core import Brotr
    from services import Finder

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

    async with brotr.pool:
        async with finder:
            await finder.run_forever()
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp
from nostr_sdk import RelayUrl
from pydantic import BaseModel, Field

from core.service import BaseService, BaseServiceConfig
from models import Relay


if TYPE_CHECKING:
    import ssl

    from core.brotr import Brotr


# Nostr event kinds for relay discovery (NIP-01, NIP-02)
_KIND_RECOMMEND_RELAY = 2  # Deprecated: NIP-01 recommend relay
_KIND_CONTACTS = 3  # NIP-02 contact list with relay URLs

# Minimum tag length (name + at least one value)
_MIN_TAG_LENGTH = 2


# =============================================================================
# Configuration
# =============================================================================


class ConcurrencyConfig(BaseModel):
    """Concurrency limits for parallel API requests."""

    max_parallel: int = Field(default=5, ge=1, le=20, description="Maximum concurrent API requests")


class EventsConfig(BaseModel):
    """Event scanning configuration for discovering relay URLs from stored events.

    Requires a full database schema with ``tags``, ``tagvalues``, and ``content``
    columns. Set ``enabled=false`` for minimal-schema implementations (e.g., LilBrotr).
    """

    enabled: bool = Field(
        default=True,
        description="Enable event scanning (requires full schema with tags/content columns)",
    )
    batch_size: int = Field(
        default=1000, ge=100, le=10000, description="Events to process per batch"
    )
    kinds: list[int] = Field(
        default_factory=lambda: [2, 3, 10002],
        description="Event kinds to scan (2=recommend relay, 3=contacts, 10002=relay list)",
    )


class ApiSourceConfig(BaseModel):
    """Single API source configuration."""

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=0.1, le=120.0, description="Request timeout")


class ApiConfig(BaseModel):
    """API fetching configuration - discovers relay URLs from public APIs."""

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
    """Finder service configuration."""

    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


# =============================================================================
# Service
# =============================================================================


class Finder(BaseService[FinderConfig]):
    """Relay discovery service.

    Discovers Nostr relay URLs from external APIs and stored database events,
    then inserts them as validation candidates for the Validator service.
    """

    SERVICE_NAME: ClassVar[str] = "finder"
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
        cycle_start = time.time()
        self._found_relays = 0

        # Discover relay URLs from event scanning
        if self._config.events.enabled:
            await self._find_from_events()

        # Discover relay URLs from APIs
        if self._config.api.enabled:
            await self._find_from_api()

        elapsed = time.time() - cycle_start
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
            relay_rows = await self._brotr.pool.fetch("SELECT url FROM relays ORDER BY url")
        except Exception as e:
            self._logger.warning("fetch_relays_failed", error=str(e), error_type=type(e).__name__)
            return

        if not relay_rows:
            self._logger.debug("no_relays_to_scan")
            return

        self._logger.debug("events_scan_started", relay_count=len(relay_rows))

        for relay_row in relay_rows:
            if not self.is_running:
                break

            relay_url = relay_row["url"]
            relay_events, relay_relays = await self._scan_relay_events(relay_url)
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

    async def _scan_relay_events(self, relay_url: str) -> tuple[int, int]:
        """
        Scan events from a single relay using cursor-based pagination.

        Args:
            relay_url: The relay URL to scan events from

        Returns:
            Tuple of (events_scanned, relays_found)
        """
        events_scanned = 0
        relays_found = 0

        # Load cursor for this relay
        results = await self._brotr.get_service_data(self.SERVICE_NAME, "cursor", relay_url)
        last_seen_at = results[0].get("value", {}).get("last_seen_at", 0) if results else 0

        # Query events from this relay after cursor position
        # Uses events_relays.seen_at for cursor to handle historical events correctly
        query = """
            SELECT e.id, e.created_at, e.kind, e.tags, e.content, er.seen_at
            FROM events e
            INNER JOIN events_relays er ON e.id = er.event_id
            WHERE er.relay_url = $1
              AND er.seen_at > $2
              AND (e.kind = ANY($3) OR e.tagvalues @> ARRAY['r'])
            ORDER BY er.seen_at ASC
            LIMIT $4
        """

        while self.is_running:
            relays: dict[str, Relay] = {}  # url -> Relay for deduplication
            chunk_events = 0
            chunk_last_seen_at = None

            try:
                rows = await self._brotr.pool.fetch(
                    query,
                    relay_url,
                    last_seen_at,
                    self._config.events.kinds,
                    self._config.events.batch_size,
                )
            except Exception as e:
                self._logger.warning(
                    "relay_event_query_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    relay=relay_url,
                )
                break

            if not rows:
                break

            for row in rows:
                chunk_events += 1
                kind = row["kind"]
                tags = row["tags"]
                content = row["content"]
                seen_at = row["seen_at"]

                chunk_last_seen_at = seen_at

                # Extract relay URLs from tags (r-tags)
                if tags:
                    for tag in tags:
                        if isinstance(tag, list) and len(tag) >= _MIN_TAG_LENGTH:
                            tag_name = tag[0]
                            if tag_name == "r":
                                url = tag[1]
                                validated = self._validate_relay_url(url)
                                if validated:
                                    relays[validated.url] = validated

                # Kind 2: content is the relay URL (deprecated NIP)
                if kind == _KIND_RECOMMEND_RELAY and content:
                    validated = self._validate_relay_url(content.strip())
                    if validated:
                        relays[validated.url] = validated

                # Kind 3: content may be JSON with relay URLs as keys
                if kind == _KIND_CONTACTS and content:
                    try:
                        relay_data = json.loads(content)
                        if isinstance(relay_data, dict):
                            for url in relay_data:
                                validated = self._validate_relay_url(url)
                                if validated:
                                    relays[validated.url] = validated
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Insert discovered relays as candidates
            if relays:
                try:
                    now = int(time.time())
                    records: list[tuple[str, str, str, dict[str, Any]]] = [
                        (
                            "validator",
                            "candidate",
                            relay.url,
                            {
                                "failed_attempts": 0,
                                "network": relay.network.value,
                                "inserted_at": now,
                            },
                        )
                        for relay in relays.values()
                    ]
                    await self._brotr.upsert_service_data(records)
                    relays_found += len(relays)
                except Exception as e:
                    self._logger.error(
                        "insert_candidates_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(relays),
                    )

            events_scanned += chunk_events

            # Update cursor for this relay
            if chunk_last_seen_at is not None:
                last_seen_at = chunk_last_seen_at
                await self._brotr.upsert_service_data(
                    [(self.SERVICE_NAME, "cursor", relay_url, {"last_seen_at": last_seen_at})]
                )

            # Stop if chunk wasn't full
            if chunk_events < self._config.events.batch_size:
                break

        return events_scanned, relays_found

    def _validate_relay_url(self, url: str) -> Relay | None:
        """
        Validate and normalize a relay URL.

        Args:
            url: Potential relay URL string

        Returns:
            Relay object if valid, None otherwise
        """
        if not url or not isinstance(url, str):
            return None

        url = url.strip()
        if not url:
            return None

        try:
            return Relay(url)
        except Exception:
            return None

    async def _find_from_api(self) -> None:
        """Discover relay URLs from configured external API endpoints.

        Fetches each enabled API source sequentially (with a configurable delay
        between requests), deduplicates the results, and inserts discovered
        URLs as validation candidates.
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
                    if self._config.api.delay_between_requests > 0 and i < len(enabled_sources) - 1:
                        await asyncio.sleep(self._config.api.delay_between_requests)

                except Exception as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

        # Insert as validation candidates (service_name='validator')
        if relays:
            try:
                now = int(time.time())
                records: list[tuple[str, str, str, dict[str, Any]]] = [
                    (
                        "validator",
                        "candidate",
                        relay.url,
                        {"failed_attempts": 0, "network": relay.network.value, "inserted_at": now},
                    )
                    for relay in relays.values()
                ]
                await self._brotr.upsert_service_data(records)
                self._found_relays += len(relays)
            except Exception as e:
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
            connect=min(10.0, source.timeout),
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
                        except Exception:
                            self._logger.debug("invalid_relay_url", url=item)
                    else:
                        self._logger.debug("unexpected_item_type", url=source.url, item=item)
            else:
                self._logger.debug("unexpected_api_response", url=source.url, data=data)

        return relays
