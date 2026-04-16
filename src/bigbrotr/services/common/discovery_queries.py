"""Discovery-specific database queries shared by Seeder and Finder."""

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


async def insert_relays_as_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Insert new validation candidates, skipping known relays and duplicates."""
    urls = [relay.url for relay in relays]
    if not urls:
        return 0

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
    new_relays = [relay for relay in relays if relay.url in new_urls]
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
    return await ServiceStateStore(brotr).upsert(
        [ServiceStateStore.encode_candidate(record) for record in records]
    )
