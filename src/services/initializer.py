"""
Initializer Service for BigBrotr.

Seeds initial relay data as candidates for validation.
This is a one-shot service that runs once at startup.

Usage:
    from core import Brotr
    from services import Initializer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    initializer = Initializer.from_yaml("yaml/services/initializer.yaml", brotr=brotr)

    async with brotr.pool:
        await initializer.run()
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from core.base_service import BaseService
from models import Relay

if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class SeedConfig(BaseModel):
    """Seed data configuration."""

    enabled: bool = Field(default=True, description="Enable seeding")
    file_path: str = Field(default="data/seed_relays.txt", description="Seed file path")


class InitializerConfig(BaseModel):
    """Initializer configuration."""

    seed: SeedConfig = Field(default_factory=SeedConfig)


# =============================================================================
# Service
# =============================================================================


class Initializer(BaseService):
    """
    Database initialization service.

    Seeds initial relay data as candidates for validation.
    This is a one-shot service - run once at startup.
    """

    SERVICE_NAME = "initializer"
    CONFIG_CLASS = InitializerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[InitializerConfig] = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Run initialization sequence."""
        self._logger.info("run_started")
        start_time = time.time()

        if self._config.seed.enabled:
            await self._seed_relays()

        duration = time.time() - start_time

        self._logger.info("run_completed", duration_s=round(duration, 2))

    # -------------------------------------------------------------------------
    # Seed Data
    # -------------------------------------------------------------------------

    def _parse_seed_file(self, path: Path) -> list[Relay]:
        """
        Parse seed file and validate relay URLs.

        Args:
            path: Path to the seed file

        Returns:
            List of validated Relay objects
        """
        relays: list[Relay] = []

        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    relays.append(Relay(line))
                except Exception as e:
                    self._logger.warning("seed_parse_relay_failed", error=str(e), error_type=type(e).__name__, line=line)

        return relays

    async def _seed_relays(self) -> None:
        """
        Load and insert seed relay data as candidates for validation.

        Only adds relays that are not already in the relays table and not
        already candidates in service_data. Filtering is done server-side
        for efficiency. Batch inserts with granular retry.
        """
        path = Path(self._config.seed.file_path)

        if not path.exists():
            self._logger.warning("seed_file_not_found", path=str(path))
            return

        relays = self._parse_seed_file(path)

        if not relays:
            self._logger.info("seed_no_valid_relays")
            return

        # Filter server-side: exclude URLs already in relays or service_data
        all_urls = [relay.url_without_scheme for relay in relays]

        new_urls_rows = await self._brotr.pool.fetch(
            """
            SELECT url FROM unnest($1::text[]) AS url
            WHERE url NOT IN (SELECT r.url FROM relays r)
              AND url NOT IN (
                  SELECT key FROM service_data
                  WHERE service_name = 'validator' AND data_type = 'candidate'
              )
            """,
            all_urls,
            timeout=self._brotr.config.timeouts.query,
        )
        new_urls = {row["url"] for row in new_urls_rows}

        skipped_count = len(relays) - len(new_urls)
        if skipped_count > 0:
            self._logger.info(
                "seed_skipped_existing",
                total=len(relays),
                skipped=skipped_count,
                new=len(new_urls),
            )

        if not new_urls:
            self._logger.info("seed_all_relays_exist")
            return

        # Build records for new URLs only
        records = [
            ("validator", "candidate", url, {"failed_attempts": 0})
            for url in new_urls
        ]

        # Batch insert
        batch_size = self._brotr.config.batch.max_batch_size
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            await self._brotr.upsert_service_data(batch)

        self._logger.info("seed_completed", count=len(new_urls))
