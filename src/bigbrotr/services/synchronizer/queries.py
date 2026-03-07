"""Synchronizer-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.utils import parse_relay_row


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.event_relay import EventRelay
    from bigbrotr.models.relay import Relay


async def fetch_relays(brotr: Brotr) -> list[Relay]:
    """Fetch all relays from the database as domain objects.

    Rows that fail ``Relay`` construction (invalid URL) are silently
    skipped.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        List of [Relay][bigbrotr.models.relay.Relay] instances ordered
        by ``discovered_at`` ascending.
    """
    rows = await brotr.fetch(
        """
        SELECT url, network, discovered_at
        FROM relay
        ORDER BY discovered_at ASC
        """,
    )
    relays: list[Relay] = []
    for row in rows:
        relay = parse_relay_row(row)
        if relay is not None:
            relays.append(relay)
    return relays


async def delete_stale_cursors(brotr: Brotr) -> int:
    """Remove cursor state for relays that no longer exist.

    Deletes CURSOR records whose ``state_key`` does not match any relay in
    the relay table.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        Number of deleted rows.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.SYNCHRONIZER,
        ServiceStateType.CURSOR,
    )
    return count


async def insert_event_relays(brotr: Brotr, records: list[EventRelay]) -> int:
    """Batch-insert event-relay junction records.

    Splits *records* into batches respecting
    [BatchConfig.max_size][bigbrotr.core.brotr.BatchConfig] and delegates
    each chunk to
    [Brotr.insert_event_relay()][bigbrotr.core.brotr.Brotr.insert_event_relay]
    (cascade mode).

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        records: [EventRelay][bigbrotr.models.event_relay.EventRelay]
            instances to insert.

    Returns:
        Number of new event-relay records inserted.
    """
    if not records:
        return 0
    total = 0
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        total += await brotr.insert_event_relay(records[i : i + batch_size])
    return total
