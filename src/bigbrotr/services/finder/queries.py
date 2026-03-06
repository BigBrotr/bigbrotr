"""Finder-specific database queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.types import ApiCheckpoint, EventRelayCursor


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


logger = logging.getLogger(__name__)


async def fetch_event_relay_cursors(brotr: Brotr) -> list[EventRelayCursor]:
    """Fetch all relays with their event-scanning cursor position.

    Performs a single ``LEFT JOIN`` between the ``relay`` table and
    ``service_state`` (filtered on ``finder`` / ``cursor``), returning an
    [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor] for
    every relay.  Relays without a stored cursor get
    ``seen_at=None, event_id=None`` (scan from beginning).

    Cursor rows with corrupt data (non-integer ``seen_at``, non-hex
    ``event_id``) are silently treated as missing and the relay will be
    rescanned from the beginning.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.

    Returns:
        List of
        [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor],
        one per relay in the database.
    """
    rows = await brotr.fetch(
        """
        SELECT r.url,
               (ss.state_value->>'seen_at') AS seen_at,
               ss.state_value->>'event_id' AS event_id
        FROM relay r
        LEFT JOIN service_state ss ON
            ss.service_name = $1
            AND ss.state_type = $2
            AND ss.state_key = r.url
        ORDER BY r.url
        """,
        ServiceName.FINDER,
        ServiceStateType.CURSOR,
    )
    cursors: list[EventRelayCursor] = []
    for row in rows:
        url = row["url"]
        seen_at_raw = row["seen_at"]
        event_id_hex = row["event_id"]
        if seen_at_raw is not None and event_id_hex is not None:
            try:
                cursors.append(
                    EventRelayCursor(
                        relay_url=url,
                        seen_at=int(seen_at_raw),
                        event_id=bytes.fromhex(str(event_id_hex)),
                    )
                )
            except (ValueError, TypeError):
                logger.warning("invalid_cursor_skipped: %s", url)
                cursors.append(EventRelayCursor(relay_url=url))
        else:
            cursors.append(EventRelayCursor(relay_url=url))
    return cursors


async def scan_event_relay(
    brotr: Brotr,
    cursor: EventRelayCursor,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan event-relay rows for a specific relay, cursor-paginated.

    Uses a composite cursor ``(seen_at, event_id)`` for deterministic
    pagination that handles ties in ``seen_at``. When the cursor has
    ``seen_at=None`` (new cursor), scanning starts from the beginning.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
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
          AND ($2::bigint IS NULL OR (er.seen_at, e.id) > ($2::bigint, $3::bytea))
        ORDER BY er.seen_at ASC, e.id ASC
        LIMIT $4
        """,
        cursor.relay_url,
        cursor.seen_at,
        cursor.event_id,
        limit,
    )
    return [dict(row) for row in rows]


async def load_api_checkpoints(brotr: Brotr, urls: list[str]) -> list[ApiCheckpoint]:
    """Load per-source API timestamps from CHECKPOINT records.

    Fetches CHECKPOINT records for the given source URLs and returns them
    as typed [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
    instances.  Records that cannot be parsed (missing or non-integer
    ``timestamp``) are silently skipped.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        urls: Source URLs to load checkpoints for.

    Returns:
        List of [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint],
        one per valid stored record.
    """
    if not urls:
        return []
    rows = await brotr.fetch(
        """
        SELECT state_key, state_value
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND state_key = ANY($3::text[])
        """,
        ServiceName.FINDER,
        ServiceStateType.CHECKPOINT,
        urls,
    )
    checkpoints: list[ApiCheckpoint] = []
    for r in rows:
        try:
            checkpoints.append(
                ApiCheckpoint(key=r["state_key"], timestamp=int(r["state_value"]["timestamp"]))
            )
        except (KeyError, ValueError, TypeError):
            continue
    return checkpoints


async def save_api_checkpoints(brotr: Brotr, checkpoints: list[ApiCheckpoint]) -> None:
    """Persist per-source API timestamps as CHECKPOINT records.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        checkpoints: [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
            instances to persist.
    """
    await brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=cp.key,
                state_value={"timestamp": cp.timestamp},
            )
            for cp in checkpoints
        ]
    )


async def save_event_relay_cursor(brotr: Brotr, cursor: EventRelayCursor) -> None:
    """Persist the scan cursor position for a relay.

    No-op if the cursor has no position (``seen_at`` or ``event_id`` is
    ``None``), which indicates the relay would restart from the beginning —
    storing that is pointless.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
            with relay URL and pagination position.
    """
    if cursor.seen_at is None or cursor.event_id is None:
        return
    await brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CURSOR,
                state_key=cursor.relay_url,
                state_value={
                    "seen_at": cursor.seen_at,
                    "event_id": cursor.event_id.hex(),
                },
            )
        ]
    )


async def delete_stale_cursors(brotr: Brotr) -> int:
    """Delete CURSOR records whose relay no longer exists in the relay table.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.

    Returns:
        Number of stale cursor records deleted.
    """
    rows = await brotr.fetch(
        """
        DELETE FROM service_state ss
        WHERE ss.service_name = $1
          AND ss.state_type = $2
          AND NOT EXISTS (
              SELECT 1 FROM relay r WHERE r.url = ss.state_key
          )
        RETURNING 1
        """,
        ServiceName.FINDER,
        ServiceStateType.CURSOR,
    )
    return len(rows)


async def delete_stale_api_checkpoints(brotr: Brotr, active_urls: list[str]) -> int:
    """Delete CHECKPOINT records for API sources no longer in the config.

    Args:
        brotr: The [Brotr][bigbrotr.core.brotr.Brotr] database facade.
        active_urls: Currently configured source URLs to keep.

    Returns:
        Number of stale checkpoint records deleted.
    """
    rows = await brotr.fetch(
        """
        DELETE FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND NOT (state_key = ANY($3::text[]))
        RETURNING 1
        """,
        ServiceName.FINDER,
        ServiceStateType.CHECKPOINT,
        active_urls,
    )
    return len(rows)
