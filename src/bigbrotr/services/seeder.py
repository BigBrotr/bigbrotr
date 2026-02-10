"""Seeder service for BigBrotr.

Seeds initial relay URLs into the database as candidates for validation.
This is a one-shot service intended to run once at startup to bootstrap
the relay discovery pipeline.

Relay URLs are read from a text file (one URL per line) and can be
inserted either as validation candidates (picked up by Validator) or
directly into the relays table.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Seeder

    brotr = Brotr.from_yaml("config/brotr.yaml")
    seeder = Seeder.from_yaml("config/services/seeder.yaml", brotr=brotr)

    async with brotr:
        await seeder.run()
    ```
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.models import Relay

from .common.constants import ServiceName
from .common.queries import filter_new_relay_urls, upsert_candidates


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class SeedConfig(BaseModel):
    """Configuration for seed data source and insertion mode."""

    file_path: str = Field(default="static/seed_relays.txt", description="Seed file path")
    to_validate: bool = Field(
        default=True,
        description="If True, add as candidates. If False, insert directly into relays.",
    )


class SeederConfig(BaseServiceConfig):
    """Seeder service configuration."""

    seed: SeedConfig = Field(default_factory=SeedConfig)


# =============================================================================
# Service
# =============================================================================


class Seeder(BaseService[SeederConfig]):
    """Database seeding service.

    Reads relay URLs from a seed file and inserts them into the database.
    URLs can be added as validation candidates (for Validator to process)
    or inserted directly into the relays table.

    This is a one-shot service; call ``run()`` once at startup.
    """

    SERVICE_NAME: ClassVar[str] = ServiceName.SEEDER
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
        """Execute the full seeding sequence: parse file and insert relays."""
        self._logger.info(
            "cycle_started",
            file=self._config.seed.file_path,
            to_validate=self._config.seed.to_validate,
        )
        start_time = time.monotonic()

        await self._seed()

        duration = time.monotonic() - start_time
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
                except (ValueError, TypeError) as e:
                    self._logger.warning("relay_parse_failed", url=url, error=str(e))

        return relays

    async def _seed(self) -> None:
        """Load seed file and dispatch to the appropriate insertion method."""
        path = Path(self._config.seed.file_path)

        if not await asyncio.to_thread(path.exists):
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
        """Add relays as validation candidates in the service_state table.

        Filters out URLs that already exist in the relays table or are
        already registered as candidates, preventing duplicate work.
        """
        all_urls = [relay.url for relay in relays]

        new_url_list = await filter_new_relay_urls(
            self._brotr, all_urls, timeout=self._brotr.config.timeouts.query
        )
        new_urls = set(new_url_list)

        skipped_count = len(relays) - len(new_urls)
        if skipped_count > 0:
            self._logger.debug("existing_skipped", skipped=skipped_count)

        if not new_urls:
            self._logger.info("all_relays_exist", count=len(relays))
            return

        new_relays = [r for r in relays if r.url in new_urls]
        count = await upsert_candidates(self._brotr, new_relays)
        self._logger.info("candidates_inserted", count=count)

    async def _seed_as_relays(self, relays: list[Relay]) -> None:
        """Insert relays directly into the relays table.

        Uses ON CONFLICT DO NOTHING so duplicates are silently skipped.
        """
        batch_size = self._brotr.config.batch.max_size
        inserted = 0

        for i in range(0, len(relays), batch_size):
            batch = relays[i : i + batch_size]
            count = await self._brotr.insert_relay(batch)
            inserted += count
            self._logger.debug("batch_inserted", batch_num=i // batch_size + 1, count=count)

        self._logger.info("relays_inserted", total=len(relays), inserted=inserted)
