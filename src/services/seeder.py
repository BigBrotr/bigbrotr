"""
Seeder Service for BigBrotr.

Seeds initial relay data as candidates for validation.
This is a one-shot service that runs once at startup.

Usage:
    from core import Brotr
    from services import Seeder

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    seeder = Seeder.from_yaml("yaml/services/seeder.yaml", brotr=brotr)

    async with brotr.pool:
        await seeder.run()
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from core.base_service import BaseService, BaseServiceConfig
from models import Relay


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class SeedConfig(BaseModel):
    """Seed data configuration."""

    file_path: str = Field(default="static/seed_relays.txt", description="Seed file path")
    to_validate: bool = Field(
        default=True,
        description="If True, add as candidates. If False, insert directly into relays.",
    )


class SeederConfig(BaseServiceConfig):
    """Seeder configuration."""

    seed: SeedConfig = Field(default_factory=SeedConfig)


# =============================================================================
# Service
# =============================================================================


class Seeder(BaseService[SeederConfig]):
    """
    Database seeding service.

    Seeds initial relay data as candidates for validation.
    This is a one-shot service - run once at startup.
    """

    SERVICE_NAME: ClassVar[str] = "seeder"
    CONFIG_CLASS: ClassVar[type[SeederConfig]] = SeederConfig

    def __init__(
        self,
        brotr: Brotr,
        config: SeederConfig | None = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Run seeding sequence."""
        self._logger.info(
            "cycle_started",
            file=self._config.seed.file_path,
            to_validate=self._config.seed.to_validate,
        )
        start_time = time.time()

        await self._seed()

        duration = time.time() - start_time
        self._logger.info("cycle_completed", duration_s=round(duration, 2))

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
                url = line.strip()
                if not url or url.startswith("#"):
                    continue
                try:
                    relays.append(Relay(url))
                except Exception as e:
                    self._logger.warning("relay_parse_failed", url=url, error=str(e))

        return relays

    async def _seed(self) -> None:
        """Load and insert seed relay data."""
        path = Path(self._config.seed.file_path)

        if not path.exists():
            self._logger.warning("file_not_found", path=str(path))
            return

        relays = self._parse_seed_file(path)
        self._logger.debug("file_parsed", path=str(path), count=len(relays))

        if not relays:
            self._logger.info("no_valid_relays")
            return

        if self._config.seed.to_validate:
            await self._seed_as_candidates(relays)
        else:
            await self._seed_as_relays(relays)

    async def _seed_as_candidates(self, relays: list[Relay]) -> None:
        """
        Add relays as validation candidates.

        Filters against both relays table and existing candidates in service_data.
        """
        all_urls = [relay.url for relay in relays]

        new_urls_rows = await self._brotr.pool.fetch(
            """
            SELECT url FROM unnest($1::text[]) AS url
            WHERE url NOT IN (SELECT r.url FROM relays r)
              AND url NOT IN (
                  SELECT data_key FROM service_data
                  WHERE service_name = 'validator' AND data_type = 'candidate'
              )
            """,
            all_urls,
            timeout=self._brotr.config.timeouts.query,
        )
        new_urls = {row["url"] for row in new_urls_rows}

        skipped_count = len(relays) - len(new_urls)
        if skipped_count > 0:
            self._logger.debug("existing_skipped", skipped=skipped_count)

        if not new_urls:
            self._logger.info("all_relays_exist", count=len(relays))
            return

        now = int(time.time())
        records: list[tuple[str, str, str, dict[str, Any]]] = [
            (
                "validator",
                "candidate",
                relay.url,
                {"failed_attempts": 0, "network": relay.network.value, "inserted_at": now},
            )
            for relay in relays
            if relay.url in new_urls
        ]
        batch_size = self._brotr.config.batch.max_batch_size

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            await self._brotr.upsert_service_data(batch)
            self._logger.debug("batch_inserted", batch_num=i // batch_size + 1, count=len(batch))

        self._logger.info("candidates_inserted", count=len(new_urls))

    async def _seed_as_relays(self, relays: list[Relay]) -> None:
        """
        Insert relays directly into relays table.

        Uses ON CONFLICT DO NOTHING, so duplicates are silently skipped.
        """
        batch_size = self._brotr.config.batch.max_batch_size
        inserted = 0

        for i in range(0, len(relays), batch_size):
            batch = relays[i : i + batch_size]
            count = await self._brotr.insert_relays(batch)
            inserted += count
            self._logger.debug("batch_inserted", batch_num=i // batch_size + 1, count=count)

        self._logger.info("relays_inserted", total=len(relays), inserted=inserted)
