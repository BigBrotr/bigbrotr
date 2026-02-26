"""Seeder service for BigBrotr.

Seeds initial relay URLs into the database as candidates for validation.
This is a one-shot service intended to run once at startup to bootstrap
relay discovery.

Relay URLs are read from a text file (one URL per line) and can be
inserted either as validation candidates (picked up by
[Validator][bigbrotr.services.validator.Validator]) or directly into
the relays table.

Note:
    The seeder is the only one-shot service. Call
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
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.queries import insert_candidates, insert_relays

from .configs import SeederConfig
from .utils import parse_seed_file


if TYPE_CHECKING:
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
        [Finder][bigbrotr.services.finder.Finder]: Discovers additional
            relay URLs continuously.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.SEEDER
    CONFIG_CLASS: ClassVar[type[SeederConfig]] = SeederConfig

    async def run(self) -> None:
        """Execute the full seeding sequence: parse file and insert relays."""
        self._logger.info(
            "cycle_started",
            file=self._config.seed.file_path,
            to_validate=self._config.seed.to_validate,
        )
        inserted = await self.seed()
        self._logger.info("cycle_completed", inserted=inserted)

    async def seed(self) -> int:
        """Parse the seed file and insert relays.

        Reads relay URLs from the configured seed file, validates them,
        then inserts them as validation candidates or directly into the
        relays table based on the ``to_validate`` configuration flag.

        Returns:
            Number of relays inserted.
        """
        path = Path(self._config.seed.file_path)
        relays = await asyncio.to_thread(parse_seed_file, path)
        self._logger.debug("file_parsed", path=str(path), count=len(relays))

        if not relays:
            self._logger.info("no_valid_relays")
            return 0

        if self._config.seed.to_validate:
            return await self._seed_as_candidates(relays)
        return await self._seed_as_relays(relays)

    async def _seed_as_candidates(self, relays: list[Relay]) -> int:
        """Insert relays as validation candidates in ``service_state``."""
        try:
            count = await insert_candidates(self._brotr, relays)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.error(
                "candidates_insert_failed",
                error=str(e),
                error_type=type(e).__name__,
                total=len(relays),
            )
            return 0
        self._logger.info("candidates_inserted", total=len(relays), inserted=count)
        return count

    async def _seed_as_relays(self, relays: list[Relay]) -> int:
        """Insert relays directly into the relays table."""
        try:
            count = await insert_relays(self._brotr, relays)
        except (asyncpg.PostgresError, OSError) as e:
            self._logger.error(
                "relays_insert_failed",
                error=str(e),
                error_type=type(e).__name__,
                total=len(relays),
            )
            return 0
        self._logger.info("relays_inserted", total=len(relays), inserted=count)
        return count
