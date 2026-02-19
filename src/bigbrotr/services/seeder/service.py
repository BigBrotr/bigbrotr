"""Seeder service for BigBrotr.

Seeds initial relay URLs into the database as candidates for validation.
This is a one-shot service intended to run once at startup to bootstrap
the relay discovery pipeline.

Relay URLs are read from a text file (one URL per line) and can be
inserted either as validation candidates (picked up by
[Validator][bigbrotr.services.validator.Validator]) or directly into
the relays table.

Note:
    The seeder is the only one-shot service in the pipeline. Call
    ``run()`` once at startup; do not use ``run_forever()``. In the
    default configuration (``to_validate=True``), seed URLs are inserted
    as candidates in ``service_state`` so that the
    [Validator][bigbrotr.services.validator.Validator] verifies them
    before promoting to the ``relay`` table.

See Also:
    [SeederConfig][bigbrotr.services.seeder.SeederConfig]: Configuration
        model for seed file path and insertion mode.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()`` and ``from_yaml()`` lifecycle.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for relay
        insertion.
    [insert_candidates][bigbrotr.services.common.queries.insert_candidates]:
        Query used to insert seed URLs as validation candidates.

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

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.queries import insert_candidates

from .configs import SeederConfig
from .utils import parse_seed_file


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


class Seeder(BaseService[SeederConfig]):
    """Database seeding service.

    Reads relay URLs from a seed file and inserts them into the database.
    URLs can be added as validation candidates (for
    [Validator][bigbrotr.services.validator.Validator] to process) or
    inserted directly into the relays table.

    This is a one-shot service; call ``run()`` once at startup.

    See Also:
        [SeederConfig][bigbrotr.services.seeder.SeederConfig]: Configuration
            model for this service.
        [Finder][bigbrotr.services.finder.Finder]: The next stage in the
            pipeline that discovers additional relay URLs continuously.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.SEEDER
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

    async def _seed(self) -> None:
        """Load seed file and dispatch to the appropriate insertion method."""
        path = Path(self._config.seed.file_path)

        if not await asyncio.to_thread(path.exists):
            self._logger.warning("file_not_found", path=str(path))
            return

        relays = parse_seed_file(path)
        self._logger.debug("file_parsed", path=str(path), count=len(relays))

        if not relays:
            self._logger.info("no_valid_relays")
            return

        if self._config.seed.to_validate:
            await self._seed_as_candidates(relays)
        else:
            await self._seed_as_relays(relays)

    async def _seed_as_candidates(self, relays: list[Relay]) -> None:
        """Add relays as validation candidates in the ``service_state`` table.

        Uses [insert_candidates][bigbrotr.services.common.queries.insert_candidates]
        which internally filters out URLs already in the ``relay`` table
        or registered as candidates.
        """
        count = await insert_candidates(self._brotr, relays)
        if count == 0:
            self._logger.info("all_relays_exist", count=len(relays))
        else:
            self._logger.info("candidates_inserted", count=count)

    async def _seed_as_relays(self, relays: list[Relay]) -> None:
        """Insert relays directly into the relays table.

        Uses ``ON CONFLICT DO NOTHING`` so duplicates are silently skipped.
        Bypasses the [Validator][bigbrotr.services.validator.Validator]
        pipeline entirely.

        Warning:
            Relays inserted via this path skip WebSocket validation.
            Use ``to_validate=True`` (the default) unless you are certain
            the seed URLs are valid Nostr relays.
        """
        batch_size = self._brotr.config.batch.max_size
        inserted = 0

        for i in range(0, len(relays), batch_size):
            batch = relays[i : i + batch_size]
            count = await self._brotr.insert_relay(batch)
            inserted += count
            self._logger.debug("batch_inserted", batch_num=i // batch_size + 1, count=count)

        self._logger.info("relays_inserted", total=len(relays), inserted=inserted)
