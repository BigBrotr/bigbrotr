"""Synchronizer-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.queries import batched_insert
from bigbrotr.services.common.state_store import ServiceStateStore, cursor_from_payload
from bigbrotr.services.common.types import SyncCursor


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.event_relay import EventRelay


async def fetch_cursors_to_sync(
    brotr: Brotr, end: int, networks: Sequence[NetworkType]
) -> list[SyncCursor]:
    """Fetch sync cursors for relays on the given networks, ordered by timestamp ascending.

    Performs a LEFT JOIN between the relay table and the synchronizer's
    cursor state in ``service_state``. Only relays whose network is in
    ``networks`` are included. Relays without a cursor get a default
    cursor (``timestamp=0``). Relays already synced past ``end`` are excluded.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        end: Upper bound timestamp — relays synced past this are excluded.
        networks: Network types to include (e.g. enabled networks from config).

    Returns:
        List of [SyncCursor][bigbrotr.services.common.types.SyncCursor]
        ordered by timestamp ascending (oldest first).
    """
    rows = await brotr.fetch(
        """
        WITH cursors AS (
            SELECT state_key,
                   state_value,
                   (state_value->>'timestamp')::bigint AS ts,
                   state_value->>'id' AS cursor_id
            FROM service_state
            WHERE service_name = $1
              AND state_type = $2
        )
        SELECT r.url, c.state_value
        FROM relay r
        LEFT JOIN cursors c ON c.state_key = r.url
        WHERE r.network = ANY($4)
          AND (c.ts IS NULL OR c.ts <= $3)
        ORDER BY COALESCE(c.ts, 0) ASC,
                 COALESCE(c.cursor_id, repeat('0', 64)) ASC
        """,
        ServiceName.SYNCHRONIZER,
        ServiceStateType.CURSOR,
        end,
        [n.value for n in networks],
    )
    results: list[SyncCursor] = []
    for row in rows:
        sv = row["state_value"]
        if sv:
            results.append(cursor_from_payload(row["url"], sv, SyncCursor))
        else:
            results.append(SyncCursor(key=row["url"]))
    return results


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
    return await batched_insert(brotr, records, brotr.insert_event_relay)


async def upsert_sync_cursors(brotr: Brotr, cursors: Iterable[SyncCursor]) -> None:
    """Persist multiple sync cursor positions in batched upserts.

    Splits cursors into chunks of ``brotr.config.batch.max_size`` to
    respect database parameter limits.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        cursors: Iterable of [SyncCursor][bigbrotr.services.common.types.SyncCursor]
            instances to persist.
    """
    await ServiceStateStore(brotr).upsert_cursors(ServiceName.SYNCHRONIZER, list(cursors))
