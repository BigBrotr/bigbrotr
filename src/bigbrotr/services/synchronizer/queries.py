"""Synchronizer-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.paging import iter_keyset_pages
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import SyncCursor
from bigbrotr.services.common.utils import batched_insert


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.event_relay import EventRelay


_CURSOR_SENTINEL_ID = "0" * 64


def _sync_cursor_from_row(row: Any) -> SyncCursor:
    if row["state_value"]:
        return ServiceStateStore.decode_cursor(row["url"], row["state_value"], SyncCursor)
    return SyncCursor(key=row["url"])


async def count_cursors_to_sync(brotr: Brotr, end: int, networks: Sequence[NetworkType]) -> int:
    """Count relays eligible for synchronization on the selected networks."""
    count: int = await brotr.fetchval(
        """
        WITH cursors AS (
            SELECT state_key,
                   (state_value->>'timestamp')::bigint AS ts
            FROM service_state
            WHERE service_name = $1
              AND state_type = $2
        )
        SELECT count(*)::int
        FROM relay r
        LEFT JOIN cursors c ON c.state_key = r.url
        WHERE r.network = ANY($4)
          AND (c.ts IS NULL OR c.ts <= $3)
        """,
        ServiceName.SYNCHRONIZER,
        ServiceStateType.CURSOR,
        end,
        [n.value for n in networks],
    )
    return count


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
    return [_sync_cursor_from_row(row) for row in rows]


async def fetch_cursors_to_sync_page(
    brotr: Brotr,
    end: int,
    networks: Sequence[NetworkType],
    after: SyncCursor | None,
    limit: int,
) -> tuple[list[SyncCursor], SyncCursor | None]:
    """Fetch one page of sync cursors ordered by least progress first."""
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
          AND (
                $5::bigint IS NULL
                OR (
                    COALESCE(c.ts, 0),
                    COALESCE(c.cursor_id, $6::text),
                    r.url
                ) > ($5::bigint, $6::text, $7::text)
          )
        ORDER BY COALESCE(c.ts, 0) ASC,
                 COALESCE(c.cursor_id, $6::text) ASC,
                 r.url ASC
        LIMIT $8
        """,
        ServiceName.SYNCHRONIZER,
        ServiceStateType.CURSOR,
        end,
        [n.value for n in networks],
        after.timestamp if after is not None else None,
        after.id if after is not None else _CURSOR_SENTINEL_ID,
        after.key if after is not None else "",
        limit,
    )
    results = [_sync_cursor_from_row(row) for row in rows]
    next_cursor = results[-1] if results else None
    return results, next_cursor


async def iter_cursors_to_sync_pages(
    brotr: Brotr,
    end: int,
    networks: Sequence[NetworkType],
    *,
    page_size: int,
) -> AsyncIterator[list[SyncCursor]]:
    """Yield sync cursor pages without loading the full relay set."""
    async for page in iter_keyset_pages(
        lambda after, limit: fetch_cursors_to_sync_page(
            brotr,
            end,
            networks,
            after,
            limit,
        ),
        page_size=page_size,
    ):
        yield page


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
