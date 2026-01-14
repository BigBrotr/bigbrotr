"""
Finder Service for BigBrotr.

Discovers Nostr relay URLs from:
- External APIs (nostr.watch and similar)
- Database events (NIP-65 relay lists, contact lists, r-tags)

Usage:
    from core import Brotr
    from services import Finder

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

    async with brotr.pool:
        async with finder:
            await finder.run_forever(interval=3600)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp
from nostr_sdk import RelayUrl
from pydantic import BaseModel, Field

from core.base_service import BaseService, BaseServiceConfig
from models import Relay


if TYPE_CHECKING:
    import ssl

    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel API fetching."""

    max_parallel: int = Field(default=5, ge=1, le=20, description="Maximum concurrent API requests")


class EventsConfig(BaseModel):
    """
    Event scanning configuration - discovers relay URLs from stored events.

    NOTE: This feature requires a full schema with tags/tagvalues/content columns.
    Set enabled=false for LilBrotr or minimal schema implementations.
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
    """Finder configuration."""

    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


# =============================================================================
# Service
# =============================================================================


class Finder(BaseService[FinderConfig]):
    """
    Relay discovery service.

    Discovers Nostr relay URLs from:
    - External APIs (nostr.watch, etc.)
    - Database events:
        - Kind 2 (deprecated): Recommend Relay
        - Kind 3 (NIP-02): Contact list with relay hints
        - Kind 10002 (NIP-65): Relay list metadata with r-tags
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
        """
        Run single discovery cycle.

        Discovers relay URLs from configured sources (APIs, event scanning).
        Call via run_forever() for continuous operation.
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
        self._logger.info("cycle_completed", found=self._found_relays, duration=round(elapsed, 2))

    async def _find_from_events(self) -> None:
        """
        Discover relay URLs from database events using per-relay cursor-based pagination.

        For each relay in the relays table, scans events from events_relays using
        a cursor based on seen_at timestamp. This ensures that when Synchronizer
        inserts historical events, Finder will still process them since each relay
        has its own independent cursor.

        Scans events for relay URLs in:
        - Kind 2: content field contains relay URL (deprecated)
        - Kind 3: content field may contain JSON with relay URLs
        - Kind 10002: r-tags contain relay URLs (NIP-65)
        - Any event: r-tags may contain relay URLs
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
        cursor = await self._load_relay_cursor(relay_url)
        last_seen_at = cursor.get("last_seen_at", 0)

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
                        if isinstance(tag, list) and len(tag) >= 2:
                            tag_name = tag[0]
                            if tag_name == "r":
                                url = tag[1]
                                validated = self._validate_relay_url(url)
                                if validated:
                                    relays[validated.url] = validated

                # Kind 2: content is the relay URL (deprecated NIP)
                if kind == 2 and content:
                    validated = self._validate_relay_url(content.strip())
                    if validated:
                        relays[validated.url] = validated

                # Kind 3: content may be JSON with relay URLs as keys
                if kind == 3 and content:
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
                            {"failed_attempts": 0, "network": relay.network.value, "inserted_at": now},
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
                await self._save_relay_cursor(relay_url, last_seen_at)

            # Stop if chunk wasn't full
            if chunk_events < self._config.events.batch_size:
                break

        return events_scanned, relays_found

    async def _load_relay_cursor(self, relay_url: str) -> dict[str, Any]:
        """Load the event scanning cursor for a specific relay."""
        try:
            results = await self._brotr.get_service_data(
                service_name="finder",
                data_type="cursor",
                key=relay_url,
            )
            if results:
                value: dict[str, Any] = results[0].get("value", {})
                return value
        except Exception as e:
            self._logger.warning(
                "cursor_load_failed", error=str(e), error_type=type(e).__name__, relay=relay_url
            )
        return {}

    async def _save_relay_cursor(self, relay_url: str, seen_at: int) -> None:
        """Save the event scanning cursor for a specific relay."""
        try:
            cursor_data = {"last_seen_at": seen_at}
            await self._brotr.upsert_service_data([("finder", "cursor", relay_url, cursor_data)])
        except Exception as e:
            self._logger.warning(
                "cursor_save_failed", error=str(e), error_type=type(e).__name__, relay=relay_url
            )

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
        """Discover relay URLs from external APIs."""
        # Dict of unique relay URLs discovered (url -> Relay for deduplication)
        relays: dict[str, Relay] = {}
        sources_checked = 0

        # Create SSL context based on configuration
        # verify_ssl=True (default): Use system CA bundle
        # verify_ssl=False: Disable verification (for testing/internal APIs only)
        ssl_context: ssl.SSLContext | bool = True
        if not self._config.api.verify_ssl:
            ssl_context = False
            self._logger.warning("ssl_verification_disabled")

        # Create connector with SSL configuration
        connector = aiohttp.TCPConnector(ssl=ssl_context)

        # Reuse a single ClientSession for all API requests (connection pooling)
        async with aiohttp.ClientSession(connector=connector) as session:
            enabled_sources = [s for s in self._config.api.sources if s.enabled]
            for i, source in enumerate(enabled_sources):
                # Check for graceful shutdown before each API call
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

                    # Don't delay after last source
                    if self._config.api.delay_between_requests > 0 and i < len(enabled_sources) - 1:
                        await asyncio.sleep(self._config.api.delay_between_requests)

                except Exception as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

        # Insert discovered relays as candidates for validation
        # service_name='validator' so Validator service picks them up
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
        """
        Fetch relay URLs from a single API source.

        Args:
            session: Reusable aiohttp ClientSession
            source: API source configuration

        Returns:
            List of validated RelayUrl objects
        """
        relays: list[RelayUrl] = []

        # Apply granular timeouts: connect within 10s, read within configured total
        timeout = aiohttp.ClientTimeout(
            total=source.timeout,
            connect=min(10.0, source.timeout),  # Connection timeout
            sock_read=source.timeout,  # Read timeout per socket operation
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
