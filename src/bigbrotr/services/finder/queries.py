"""Finder-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.paging import iter_keyset_pages
from bigbrotr.services.common.state_store import (
    ServiceStateStore,
    cursor_from_payload,
)
from bigbrotr.services.common.types import ApiCheckpoint, FinderCursor


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

    from bigbrotr.core.brotr import Brotr


_CURSOR_SENTINEL_ID = "0" * 64


def _finder_cursor_from_row(row: Any) -> FinderCursor:
    state_value = row["state_value"]
    if state_value:
        return cursor_from_payload(row["url"], state_value, FinderCursor)
    return FinderCursor(key=row["url"])


async def count_relays_to_find(brotr: Brotr) -> int:
    """Count relay rows eligible for event scanning."""
    count: int = await brotr.fetchval("SELECT count(*)::int FROM relay")
    return count


async def fetch_cursors_to_find(brotr: Brotr) -> list[FinderCursor]:
    """Fetch all relays with their event-scanning cursor position.

    Performs a single ``LEFT JOIN`` between the ``relay`` table and
    ``service_state`` (filtered on ``finder`` / ``cursor``), returning an
    [FinderCursor][bigbrotr.services.common.types.FinderCursor] for
    every relay.  Relays without a stored cursor get default values
    (``timestamp=0``, scan from beginning).

    Results are ordered by ``(timestamp, id)`` ascending so that relays
    with the least scanning progress are processed first.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.

    Returns:
        List of
        [FinderCursor][bigbrotr.services.common.types.FinderCursor],
        one per relay in the database, ordered by ``(timestamp, id)``.
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
        ORDER BY COALESCE(c.ts, 0) ASC,
                 COALESCE(c.cursor_id, repeat('0', 64)) ASC
        """,
        ServiceName.FINDER,
        ServiceStateType.CURSOR,
    )
    return [_finder_cursor_from_row(row) for row in rows]


async def fetch_cursors_to_find_page(
    brotr: Brotr,
    after: FinderCursor | None,
    limit: int,
) -> tuple[list[FinderCursor], FinderCursor | None]:
    """Fetch one page of relay scan cursors ordered by progress ascending."""
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
        WHERE $3::bigint IS NULL
           OR (
                COALESCE(c.ts, 0),
                COALESCE(c.cursor_id, $4::text),
                r.url
           ) > ($3::bigint, $4::text, $5::text)
        ORDER BY COALESCE(c.ts, 0) ASC,
                 COALESCE(c.cursor_id, $4::text) ASC,
                 r.url ASC
        LIMIT $6
        """,
        ServiceName.FINDER,
        ServiceStateType.CURSOR,
        after.timestamp if after is not None else None,
        after.id if after is not None else _CURSOR_SENTINEL_ID,
        after.key if after is not None else "",
        limit,
    )
    results = [_finder_cursor_from_row(row) for row in rows]
    next_cursor = results[-1] if results else None
    return results, next_cursor


async def iter_cursors_to_find_pages(
    brotr: Brotr,
    *,
    page_size: int,
) -> AsyncIterator[list[FinderCursor]]:
    """Yield finder cursor pages without materializing the full workset."""
    async for page in iter_keyset_pages(
        lambda after, limit: fetch_cursors_to_find_page(brotr, after, limit),
        page_size=page_size,
    ):
        yield page


async def scan_event_relay(
    brotr: Brotr,
    cursor: FinderCursor,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan event-relay rows for a specific relay, cursor-paginated.

    Uses a composite cursor ``(timestamp, id)`` for deterministic
    pagination that handles ties in ``seen_at``. When the cursor has
    ``timestamp=0`` (default), scanning starts from the beginning.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        cursor: [FinderCursor][bigbrotr.services.common.types.FinderCursor]
            with relay URL and pagination position.
        limit: Maximum rows per batch.

    Returns:
        List of dicts with all event columns plus ``seen_at`` from the
        ``event_relay`` junction.
    """
    rows = await brotr.fetch(
        """
        SELECT e.id AS event_id, e.pubkey, e.created_at, e.kind,
               e.tags, e.tagvalues, e.content, e.sig, er.seen_at
        FROM event e
        INNER JOIN event_relay er ON e.id = er.event_id
        WHERE er.relay_url = $1
          AND (er.seen_at, e.id) > ($2::bigint, decode($3, 'hex'))
        ORDER BY er.seen_at ASC, e.id ASC
        LIMIT $4
        """,
        cursor.key,
        cursor.timestamp,
        cursor.id,
        limit,
    )
    return [dict(row) for row in rows]


async def fetch_api_checkpoints(brotr: Brotr, urls: list[str]) -> list[ApiCheckpoint]:
    """Fetch per-source API checkpoints, returning one per URL.

    Returns an [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
    for every URL in *urls*.  URLs with a stored CHECKPOINT record get
    their persisted ``timestamp``; URLs without a record get a default
    checkpoint with ``timestamp=0`` (immediately eligible for refresh).

    Records that cannot be parsed (missing or non-integer ``timestamp``)
    are treated as missing and receive the default.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        urls: Source URLs to fetch checkpoints for.

    Returns:
        List of [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint],
        one per input URL, in the same order.
    """
    if not urls:
        return []
    return await ServiceStateStore(brotr).fetch_checkpoints(
        ServiceName.FINDER,
        urls,
        ApiCheckpoint,
    )


async def upsert_api_checkpoints(brotr: Brotr, checkpoints: list[ApiCheckpoint]) -> None:
    """Persist per-source API timestamps as CHECKPOINT records.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        checkpoints: [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
            instances to persist.
    """
    await ServiceStateStore(brotr).upsert_checkpoints(ServiceName.FINDER, checkpoints)


async def upsert_finder_cursors(brotr: Brotr, cursors: Iterable[FinderCursor]) -> None:
    """Persist multiple scan cursor positions in a single batch upsert.

    Cursors at default position (timestamp=0) are silently skipped.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        cursors: Iterable of [FinderCursor][bigbrotr.services.common.types.FinderCursor]
            instances to persist.
    """
    await ServiceStateStore(brotr).upsert_cursors(
        ServiceName.FINDER,
        list(cursors),
        skip_zero_timestamp=True,
    )


async def delete_stale_cursors(brotr: Brotr) -> int:
    """Delete CURSOR records whose relay no longer exists in the relay table.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.

    Returns:
        Number of stale cursor records deleted.
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
        ServiceName.FINDER,
        ServiceStateType.CURSOR,
    )
    return count


async def delete_stale_api_checkpoints(brotr: Brotr, active_urls: list[str]) -> int:
    """Delete CHECKPOINT records for API sources no longer in the config.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        active_urls: Currently configured source URLs to keep.

    Returns:
        Number of stale checkpoint records deleted.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND NOT (state_key = ANY($3::text[]))
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.FINDER,
        ServiceStateType.CHECKPOINT,
        active_urls,
    )
    return count
