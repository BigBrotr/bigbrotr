"""Shared database query utilities for BigBrotr services.

Provides cross-service query helpers that do real database work and are
used by more than one service's ``queries`` module.

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade that provides
        ``fetch()``, ``fetchrow()``, ``fetchval()``, ``execute()``,
        and ``transaction()`` methods used by every query function.
    [ServiceState][bigbrotr.models.service_state.ServiceState]: Dataclass
        used for candidate and cursor records in ``service_state``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import CandidateCheckpoint


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.relay import Relay


async def _filter_new_relays(
    brotr: Brotr,
    relays: list[Relay],
) -> list[Relay]:
    """Keep only relays not already in the database or pending validation."""
    urls = [r.url for r in relays]
    if not urls:
        return []

    rows = await brotr.fetch(
        """
        SELECT t.url FROM unnest($1::text[]) AS t(url)
        WHERE NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = t.url)
          AND NOT EXISTS (
              SELECT 1 FROM service_state ss
              WHERE ss.service_name = $2 AND ss.state_type = $3
                AND ss.state_key = t.url
          )
        """,
        urls,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
    )
    new_urls = {row["url"] for row in rows}
    return [r for r in relays if r.url in new_urls]


async def insert_relays_as_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Insert new validation candidates, skipping known relays and duplicates.

    Filters out URLs that already exist in the ``relay`` table or as
    pending candidates in ``service_state``, then persists only genuinely
    new records. Existing candidates retain their current state (e.g.
    ``failures`` counter is never reset).

    Called by [Seeder][bigbrotr.services.seeder.Seeder] and
    [Finder][bigbrotr.services.finder.Finder] to register newly
    discovered relay URLs for validation.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to register
            as candidates.

    Returns:
        Number of candidate records actually inserted.
    """
    new_relays = await _filter_new_relays(brotr, relays)
    if not new_relays:
        return 0

    now = int(time.time())
    records = [
        CandidateCheckpoint(
            key=relay.url,
            timestamp=now,
            network=relay.network,
            failures=0,
        )
        for relay in new_relays
    ]
    return await ServiceStateStore(brotr).upsert_candidates(records)
