"""
Finder Service for BigBrotr.

Discovers Nostr relay URLs from external APIs (nostr.watch and similar).

Usage:
    from core import Brotr
    from services import Finder

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)

    async with brotr.pool:
        async with finder:
            await finder.run_forever(interval=3600)

TODO: Add event scanning to discover relay URLs from database events.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import aiohttp
from nostr_tools import Relay, RelayValidationError
from pydantic import BaseModel, Field

from core.base_service import BaseService
from core.brotr import Brotr


SERVICE_NAME = "finder"


# =============================================================================
# Configuration
# =============================================================================


class EventsConfig(BaseModel):
    """Event scanning configuration - discovers relay URLs from stored events."""

    enabled: bool = Field(default=True, description="Enable event scanning")


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

    interval: float = Field(
        default=3600.0, ge=60.0, description="Seconds between discovery cycles"
    )
    events: EventsConfig = Field(default_factory=EventsConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)


# =============================================================================
# Service
# =============================================================================


class Finder(BaseService):
    """
    Relay discovery service.

    Discovers Nostr relay URLs from external APIs (nostr.watch, etc.).

    TODO: Add event scanning to discover relay URLs from database events.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = FinderConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[FinderConfig] = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        super().__init__(brotr=brotr, config=config or FinderConfig())
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
        """Discover relay URLs from database events."""
        # TODO: Implement event scanning logic
        pass

    async def _find_from_api(self) -> None:
        """Discover relay URLs from external APIs."""
        relays: dict[str, Relay] = {}
        sources_checked = 0

        for source in self._config.api.sources:
            if not source.enabled:
                continue

            try:
                source_relays = await self._fetch_single_api(source)
                relays.update(source_relays)
                sources_checked += 1

                self._logger.debug("api_fetched", url=source.url, count=len(source_relays))

                if self._config.api.delay_between_requests > 0:
                    await asyncio.sleep(self._config.api.delay_between_requests)

            except Exception as e:
                self._logger.warning("api_error", url=source.url, error=str(e))

        # Insert discovered relays into database (respecting Brotr batch size)
        if relays:
            current_time = int(time.time())
            relay_records = [
                {"url": r.url, "network": r.network, "inserted_at": current_time}
                for r in relays.values()
            ]

            batch_size = self._brotr.config.batch.max_batch_size
            for i in range(0, len(relay_records), batch_size):
                batch = relay_records[i : i + batch_size]
                await self._brotr.insert_relays(batch)

            self._found_relays += len(relays)

        if sources_checked > 0:
            self._logger.info("apis_completed", sources=sources_checked, relays=len(relays))

    async def _fetch_single_api(self, source: ApiSourceConfig) -> dict[str, Relay]:
        """Fetch relay URLs from a single API source."""
        relays: dict[str, Relay] = {}

        timeout = aiohttp.ClientTimeout(total=source.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(source.url) as resp:
                resp.raise_for_status()
                data = await resp.json()

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            try:
                                relay = Relay(item)
                                relays[relay.url] = relay
                            except RelayValidationError:
                                self._logger.debug("invalid_relay_url", url=item)
                        else:
                            self._logger.debug("unexpected_item_type", url=source.url, item=item)
                else:
                    self._logger.debug("unexpected_api_response", url=source.url, data=data)

        return relays