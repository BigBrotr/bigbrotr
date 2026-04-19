"""Discovery-specific database queries shared by Seeder and Finder."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import CandidateCheckpoint


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.relay import Relay


def _deduplicate_relays_by_url(relays: list[Relay]) -> list[Relay]:
    """Return relays with duplicate URLs removed, preserving first-seen order."""
    deduplicated: list[Relay] = []
    seen: set[str] = set()
    for relay in relays:
        if relay.url in seen:
            continue
        seen.add(relay.url)
        deduplicated.append(relay)
    return deduplicated


async def insert_relays_as_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Insert new validation candidates, skipping known relays and duplicates."""
    input_relays = _deduplicate_relays_by_url(relays)
    urls = [relay.url for relay in input_relays]
    if not urls:
        return 0

    rows = await brotr.fetch(
        """
        SELECT
            t.url,
            EXISTS (SELECT 1 FROM relay r WHERE r.url = t.url) AS relay_exists,
            ss.state_value
        FROM unnest($1::text[]) AS t(url)
        LEFT JOIN service_state ss
          ON ss.owner = $2
         AND ss.state_type = $3
         AND ss.state_key = t.url
        """,
        urls,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
    )
    rows_by_url = {row["url"]: row for row in rows}
    new_relays: list[Relay] = []
    for relay in input_relays:
        row = rows_by_url.get(relay.url)
        if row is None or row["relay_exists"]:
            continue
        state_value = row["state_value"]
        if state_value is not None:
            try:
                ServiceStateStore.decode_candidate(relay.url, state_value)
            except (KeyError, TypeError, ValueError):
                pass
            else:
                continue
        new_relays.append(relay)
    if not new_relays:
        return 0

    # Validator retry intervals are fractional, so round candidate insertion
    # timestamps up to avoid validating a newly discovered relay before the
    # configured minimum wait has elapsed.
    now = math.ceil(time.time())
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
