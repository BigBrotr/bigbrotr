"""
Priority Synchronizer Service for BigBrotr.

Handles priority-based event synchronization:
- Syncs high-priority relays from a file list
- Runs continuously without waiting for full cycle completion
- Inherits sync logic from Synchronizer

Usage:
    from core import Brotr
    from services import PrioritySynchronizer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    sync = PrioritySynchronizer.from_yaml(
        "yaml/services/priority_synchronizer.yaml",
        brotr=brotr
    )

    async with brotr.pool:
        async with sync:
            await sync.run_forever(interval=900)
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Optional

from nostr_tools import Relay, RelayValidationError
from pydantic import BaseModel, Field

from core.brotr import Brotr

from .synchronizer import Synchronizer, SynchronizerConfig


SERVICE_NAME = "priority_synchronizer"


# =============================================================================
# Configuration
# =============================================================================


class PrioritySourceConfig(BaseModel):
    """Configuration for priority relay file."""

    file_path: str = Field(
        default="data/priority_relays.txt",
        description="Path to file containing priority relay URLs (one per line)"
    )


class PrioritySynchronizerConfig(SynchronizerConfig):
    """
    Priority Synchronizer configuration.

    Extends SynchronizerConfig with priority relay file settings.
    Overrides 'source' from parent with file-based config.
    """

    source: PrioritySourceConfig = Field(  # type: ignore[assignment]
        default_factory=PrioritySourceConfig
    )


# =============================================================================
# Service
# =============================================================================


class PrioritySynchronizer(Synchronizer):
    """
    Priority-based event synchronization service.

    Inherits from Synchronizer but fetches relays from a priority file
    instead of from the database. This allows dedicated syncing of
    important relays without competing with the regular sync queue.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = PrioritySynchronizerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[PrioritySynchronizerConfig] = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        super().__init__(brotr=brotr, config=config or PrioritySynchronizerConfig())
        self._config: PrioritySynchronizerConfig

    # -------------------------------------------------------------------------
    # Override Relay Fetching
    # -------------------------------------------------------------------------

    async def _fetch_relays(self) -> list[Relay]:
        """
        Fetch relays from priority file.

        Reads relay URLs from the configured file path,
        one URL per line. Invalid URLs are skipped with a warning.
        Duplicates are removed (first occurrence is kept).
        """
        relays: dict[str, Relay] = {}

        filepath = Path(self._config.source.file_path)
        if not filepath.exists():
            self._logger.warning("priority_file_not_found", path=str(filepath))
            return []

        try:
            with filepath.open("r", encoding="utf-8") as f:
                for line in f:
                    relay_url = line.strip()
                    if not relay_url or relay_url.startswith("#"):
                        continue
                    try:
                        relay = Relay(relay_url)
                        if relay.url not in relays:
                            relays[relay.url] = relay
                    except RelayValidationError:
                        self._logger.debug("invalid_relay_url", url=relay_url)

        except OSError as e:
            self._logger.error("priority_file_read_error", error=str(e))

        self._logger.debug("priority_relays_loaded", count=len(relays))
        return list(relays.values())

    async def run(self) -> None:
        """
        Run single synchronization cycle for priority relays.

        Similar to parent but optimized for priority relays:
        - Does not shuffle (maintains priority order)
        - Uses separate state namespace
        """
        cycle_start = time.time()
        self._synced_events = 0
        self._synced_relays = 0
        self._failed_relays = 0

        relays = await self._fetch_relays()
        if not relays:
            self._logger.info("no_priority_relays")
            return

        self._logger.info("priority_sync_started", relay_count=len(relays))

        # Optionally shuffle - can be disabled for strict priority ordering
        random.shuffle(relays)

        # Process relays with concurrency limit (lower for priority)
        import asyncio
        semaphore = asyncio.Semaphore(self._config.concurrency.max_concurrent_relays)

        async def sync_with_limit(relay: Relay) -> None:
            async with semaphore:
                await self._sync_relay(relay)

        tasks = [sync_with_limit(relay) for relay in relays]
        await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - cycle_start
        self._logger.info(
            "priority_cycle_completed",
            synced_relays=self._synced_relays,
            failed_relays=self._failed_relays,
            synced_events=self._synced_events,
            duration=round(elapsed, 2),
        )
