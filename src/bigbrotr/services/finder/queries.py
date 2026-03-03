"""Finder-specific database queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.types import EventRelayCursor


if TYPE_CHECKING:
    from .service import Finder


logger = logging.getLogger(__name__)


async def fetch_event_relay_cursors(finder: Finder) -> list[EventRelayCursor]:
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
        finder: The [Finder][bigbrotr.services.finder.Finder] instance.

    Returns:
        List of
        [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor],
        one per relay in the database.
    """
    rows = await finder._brotr.fetch(
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
                logger.warning("Skipping invalid cursor for %s", url)
                cursors.append(EventRelayCursor(relay_url=url))
        else:
            cursors.append(EventRelayCursor(relay_url=url))
    return cursors


async def scan_event_relay(
    finder: Finder,
    cursor: EventRelayCursor,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan event-relay rows for a specific relay, cursor-paginated.

    Uses a composite cursor ``(seen_at, event_id)`` for deterministic
    pagination that handles ties in ``seen_at``. When the cursor has
    ``seen_at=None`` (new cursor), scanning starts from the beginning.

    Args:
        finder: The [Finder][bigbrotr.services.finder.Finder] instance.
        cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
            with relay URL and pagination position.
        limit: Maximum rows per batch.

    Returns:
        List of dicts with all event columns plus ``seen_at`` from the
        ``event_relay`` junction.
    """
    rows = await finder._brotr.fetch(
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


async def load_api_checkpoints(finder: Finder) -> dict[str, int]:
    """Load per-source API timestamps from CHECKPOINT records.

    Fetches all CHECKPOINT records for the Finder and extracts the
    ``timestamp`` field from each record's ``state_value``.  Records that
    cannot be parsed (missing or non-integer ``timestamp``) are silently
    skipped.

    Args:
        finder: The [Finder][bigbrotr.services.finder.Finder] instance.

    Returns:
        Mapping of state key (source URL) to Unix timestamp of last fetch.
    """
    records = await finder._brotr.get_service_state(
        ServiceName.FINDER, ServiceStateType.CHECKPOINT
    )
    state: dict[str, int] = {}
    for r in records:
        try:
            state[r.state_key] = int(r.state_value["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
    return state


async def save_api_checkpoints(finder: Finder, state: dict[str, int]) -> None:
    """Persist per-source API timestamps as CHECKPOINT records.

    Args:
        finder: The [Finder][bigbrotr.services.finder.Finder] instance.
        state: Mapping of source URL to Unix timestamp to persist.
    """
    await finder._brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=url,
                state_value={"timestamp": ts},
            )
            for url, ts in state.items()
        ]
    )


async def save_event_relay_cursor(finder: Finder, cursor: EventRelayCursor) -> None:
    """Persist the scan cursor position for a relay.

    No-op if the cursor has no position (``seen_at`` or ``event_id`` is
    ``None``), which indicates the relay would restart from the beginning —
    storing that is pointless.

    Args:
        finder: The [Finder][bigbrotr.services.finder.Finder] instance.
        cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
            with relay URL and pagination position.
    """
    if cursor.seen_at is None or cursor.event_id is None:
        return
    await finder._brotr.upsert_service_state(
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
