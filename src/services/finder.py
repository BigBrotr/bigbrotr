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
from typing import TYPE_CHECKING, Any, ClassVar, Optional

import aiohttp
from nostr_sdk import RelayUrl
from pydantic import BaseModel, Field

from core.base_service import BaseService

if TYPE_CHECKING:
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
    timeout: float = Field(default=30.0, ge=1.0, le=120.0, description="Request timeout")


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


class FinderConfig(BaseModel):
    """Finder configuration."""

    interval: float = Field(default=3600.0, ge=60.0, description="Seconds between discovery cycles")
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
        config: Optional[FinderConfig] = None,
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
        Discover relay URLs from database events using cursor-based pagination.

        Scans events for relay URLs in:
        - Kind 2: content field contains relay URL (deprecated)
        - Kind 3: content field may contain JSON with relay URLs
        - Kind 10002: r-tags contain relay URLs (NIP-65)
        - Any event: r-tags may contain relay URLs

        Uses a cursor stored in the services table to track progress.
        Processes events in chunks ordered by (created_at, id) ASC.
        """
        total_events_scanned = 0
        total_relays_found = 0
        chunks_processed = 0

        # Load cursor from services table
        cursor = await self._load_event_cursor()
        last_timestamp = cursor.get("last_timestamp", 0)
        last_id = cursor.get("last_id", b"\x00" * 32)  # Minimum bytea value

        # Convert hex string back to bytes if needed
        if isinstance(last_id, str):
            last_id = bytes.fromhex(last_id)

        self._logger.debug(
            "events_cursor_loaded",
            last_timestamp=last_timestamp,
            last_id=last_id.hex() if last_id else None,
        )

        # Process events in chunks until no more events or batch limit reached
        while True:
            relays: set[str] = set()
            chunk_events = 0

            # Query events after cursor position
            # Order by (created_at, id) ASC to ensure deterministic pagination
            # Uses composite comparison for correct cursor resumption
            query = """
                SELECT id, created_at, kind, tags, content
                FROM events
                WHERE (kind = ANY($1) OR tagvalues @> ARRAY['r'])
                  AND (created_at > $2 OR (created_at = $2 AND id > $3))
                ORDER BY created_at ASC, id ASC
                LIMIT $4
            """

            try:
                rows = await self._brotr.pool.fetch(
                    query,
                    self._config.events.kinds,
                    last_timestamp,
                    last_id,
                    self._config.events.batch_size,
                )
            except Exception as e:
                self._logger.warning(
                    "event_query_failed", error=str(e), error_type=type(e).__name__
                )
                break

            if not rows:
                # No more events to process
                break

            # Track the last event's timestamp and id for cursor
            chunk_last_timestamp = None
            chunk_last_id = None

            for row in rows:
                chunk_events += 1
                event_id = row["id"]
                created_at = row["created_at"]
                kind = row["kind"]
                tags = row["tags"]
                content = row["content"]

                # Track last processed event
                chunk_last_timestamp = created_at
                chunk_last_id = event_id

                # Extract relay URLs from tags (r-tags)
                if tags:
                    for tag in tags:
                        if isinstance(tag, list) and len(tag) >= 2:
                            tag_name = tag[0]
                            if tag_name == "r":
                                url = tag[1]
                                validated = self._validate_relay_url(url)
                                if validated:
                                    relays.add(validated)

                # Kind 2: content is the relay URL (deprecated NIP)
                if kind == 2 and content:
                    validated = self._validate_relay_url(content.strip())
                    if validated:
                        relays.add(validated)

                # Kind 3: content may be JSON with relay URLs as keys
                # Format: {"wss://relay.example.com": {"read": true, "write": true}, ...}
                if kind == 3 and content:
                    try:
                        relay_data = json.loads(content)
                        if isinstance(relay_data, dict):
                            for url in relay_data:
                                validated = self._validate_relay_url(url)
                                if validated:
                                    relays.add(validated)
                    except (json.JSONDecodeError, TypeError):
                        # Content is not JSON or not a dict, skip
                        pass

            # Insert discovered relays as candidates
            if relays:
                try:
                    records: list[tuple[str, str, str, dict[str, Any]]] = [
                        ("finder", "candidate", url, {}) for url in relays
                    ]
                    await self._brotr.upsert_service_data(records)
                    total_relays_found += len(relays)
                except Exception as e:
                    self._logger.error(
                        "insert_candidates_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(relays),
                    )

            total_events_scanned += chunk_events
            chunks_processed += 1

            # Update cursor for next iteration
            # Using composite key (created_at, id) ensures we don't miss events
            # or re-process them, even if multiple events share the same timestamp.
            # The query uses: created_at > cursor_ts OR (created_at = cursor_ts AND id > cursor_id)
            # This guarantees deterministic pagination regardless of timestamp collisions.
            if chunk_last_timestamp is not None and chunk_last_id is not None:
                last_timestamp = chunk_last_timestamp
                last_id = chunk_last_id
                await self._save_event_cursor(last_timestamp, last_id)

            self._logger.debug(
                "events_chunk_processed",
                chunk=chunks_processed,
                events=chunk_events,
                relays=len(relays),
            )

            # Stop if chunk wasn't full (no more events)
            if chunk_events < self._config.events.batch_size:
                break

        self._found_relays += total_relays_found
        self._logger.info(
            "events_completed",
            scanned=total_events_scanned,
            relays=total_relays_found,
            chunks=chunks_processed,
        )

    async def _load_event_cursor(self) -> dict[str, Any]:
        """Load the event scanning cursor from services table."""
        try:
            results = await self._brotr.get_service_data(
                service_name="finder",
                data_type="cursor",
                key="events",
            )
            if results:
                value: dict[str, Any] = results[0].get("value", {})
                return value
        except Exception as e:
            self._logger.warning("cursor_load_failed", error=str(e), error_type=type(e).__name__)
        return {}

    async def _save_event_cursor(self, timestamp: int, event_id: bytes) -> None:
        """Save the event scanning cursor to services table."""
        try:
            cursor_data = {
                "last_timestamp": timestamp,
                "last_id": event_id.hex(),  # Store as hex string for JSON
            }
            await self._brotr.upsert_service_data([("finder", "cursor", "events", cursor_data)])
        except Exception as e:
            self._logger.warning("cursor_save_failed", error=str(e), error_type=type(e).__name__)

    def _validate_relay_url(self, url: str) -> Optional[str]:
        """
        Validate and normalize a relay URL.

        Args:
            url: Potential relay URL string

        Returns:
            Normalized URL string if valid, None otherwise
        """
        if not url or not isinstance(url, str):
            return None

        url = url.strip()
        if not url:
            return None

        try:
            relay_url = RelayUrl.parse(url)
            return str(relay_url)
        except Exception:
            return None

    async def _find_from_api(self) -> None:
        """Discover relay URLs from external APIs."""
        # Set of unique relay URLs discovered
        relays: set[str] = set()
        sources_checked = 0

        # Reuse a single ClientSession for all API requests (connection pooling)
        async with aiohttp.ClientSession() as session:
            for source in self._config.api.sources:
                if not source.enabled:
                    continue

                try:
                    source_relays = await self._fetch_single_api(session, source)
                    for relay_url in source_relays:
                        relays.add(str(relay_url))
                    sources_checked += 1

                    self._logger.debug("api_fetched", url=source.url, count=len(source_relays))

                    if self._config.api.delay_between_requests > 0:
                        await asyncio.sleep(self._config.api.delay_between_requests)

                except Exception as e:
                    self._logger.warning(
                        "api_fetch_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        url=source.url,
                    )

        # Insert discovered relays as candidates in services table
        if relays:
            try:
                records: list[tuple[str, str, str, dict[str, Any]]] = [
                    ("finder", "candidate", url, {}) for url in relays
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

        timeout = aiohttp.ClientTimeout(total=source.timeout)
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
