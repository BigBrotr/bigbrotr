"""Domain-specific database queries for BigBrotr services.

All SQL queries used by services are centralized here.  Each function
accepts a Brotr instance and returns typed results.  Services import
from this module instead of writing inline SQL.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .constants import DataType, ServiceName


if TYPE_CHECKING:
    from core.brotr import Brotr
    from models.relay import Relay


# ---------------------------------------------------------------------------
# Relay Queries
# ---------------------------------------------------------------------------


async def get_all_relay_urls(brotr: Brotr) -> list[str]:
    """Fetch all relay URLs from the database, ordered alphabetically.

    Used by Finder for event-scanning relay discovery.
    """
    rows = await brotr.fetch("SELECT url FROM relays ORDER BY url")
    return [row["url"] for row in rows]


async def get_all_relays(brotr: Brotr) -> list[dict[str, Any]]:
    """Fetch all relays with their network and discovery timestamp.

    Used by Synchronizer for event collection.

    Returns:
        List of dicts with keys: ``url``, ``network``, ``discovered_at``.
    """
    rows = await brotr.fetch(
        """
        SELECT url, network, discovered_at
        FROM relays
        ORDER BY discovered_at ASC
        """
    )
    return [dict(row) for row in rows]


async def filter_new_relay_urls(
    brotr: Brotr, urls: list[str], *, timeout: float | None = None
) -> list[str]:
    """Filter URLs to those not already in relays or validator candidates.

    Used by Seeder to avoid inserting duplicates.

    Args:
        brotr: Database interface.
        urls: Candidate URLs to check.
        timeout: Query timeout override.

    Returns:
        URLs that are genuinely new (not in relays, not in candidates).
    """
    rows = await brotr.fetch(
        """
        SELECT url FROM unnest($1::text[]) AS url
        WHERE NOT EXISTS (SELECT 1 FROM relays r WHERE r.url = url)
          AND NOT EXISTS (
              SELECT 1 FROM service_data sd
              WHERE sd.service_name = $2 AND sd.data_type = $3
                AND sd.data_key = url
          )
        """,
        urls,
        ServiceName.VALIDATOR,
        DataType.CANDIDATE,
        timeout=timeout,
    )
    return [row["url"] for row in rows]


# ---------------------------------------------------------------------------
# Check / Monitoring Queries
# ---------------------------------------------------------------------------


async def count_relays_due_for_check(
    brotr: Brotr,
    service_name: str,
    threshold: int,
    networks: list[str],
    *,
    timeout: float | None = None,
) -> int:
    """Count relays needing health checks.

    Args:
        brotr: Database interface.
        service_name: Service requesting checks.
        threshold: Unix timestamp cutoff -- relays last checked before this
            are considered due.
        networks: Network type strings to include.
        timeout: Query timeout override.

    Returns:
        Number of relays due for a check.
    """
    row = await brotr.fetchrow(
        """
        SELECT COUNT(*)::int AS count
        FROM relays r
        LEFT JOIN service_data sd ON
            sd.service_name = $1
            AND sd.data_type = $2
            AND sd.data_key = r.url
        WHERE
            r.network = ANY($3)
            AND (sd.data_key IS NULL OR (sd.data->>'last_check_at')::BIGINT < $4)
        """,
        service_name,
        DataType.CHECKPOINT,
        networks,
        threshold,
        timeout=timeout,
    )
    return row["count"] if row else 0


async def fetch_relays_due_for_check(
    brotr: Brotr,
    service_name: str,
    threshold: int,
    networks: list[str],
    limit: int,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch relays due for health checks, ordered by least-recently-checked.

    Args:
        brotr: Database interface.
        service_name: Service requesting checks.
        threshold: Unix timestamp cutoff -- relays last checked before this
            are considered due.
        networks: Network type strings to include.
        limit: Maximum relays to return.
        timeout: Query timeout override.

    Returns:
        List of dicts with keys: ``url``, ``network``, ``discovered_at``.
    """
    rows = await brotr.fetch(
        """
        SELECT r.url, r.network, r.discovered_at
        FROM relays r
        LEFT JOIN service_data sd ON
            sd.service_name = $1
            AND sd.data_type = $2
            AND sd.data_key = r.url
        WHERE
            r.network = ANY($3)
            AND (sd.data_key IS NULL OR (sd.data->>'last_check_at')::BIGINT < $4)
        ORDER BY
            COALESCE((sd.data->>'last_check_at')::BIGINT, 0) ASC,
            r.discovered_at ASC
        LIMIT $5
        """,
        service_name,
        DataType.CHECKPOINT,
        networks,
        threshold,
        limit,
        timeout=timeout,
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Event Queries
# ---------------------------------------------------------------------------


async def get_events_with_relay_urls(
    brotr: Brotr,
    relay_url: str,
    last_seen_at: int,
    kinds: list[int],
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch events containing relay URLs from a specific relay.

    Retrieves events that either match discovery-relevant kinds or contain
    'r' tags, cursor-paginated by ``seen_at``.

    Used by Finder for relay discovery from stored events.

    Args:
        brotr: Database interface.
        relay_url: Source relay to scan events from.
        last_seen_at: Cursor position -- only events seen after this.
        kinds: Event kinds to include (e.g. contact lists, relay lists).
        limit: Maximum events per batch.

    Returns:
        List of event dicts with keys: ``id``, ``created_at``, ``kind``,
        ``tags``, ``content``, ``seen_at``.
    """
    rows = await brotr.fetch(
        """
        SELECT e.id, e.created_at, e.kind, e.tags, e.content, er.seen_at
        FROM events e
        INNER JOIN events_relays er ON e.id = er.event_id
        WHERE er.relay_url = $1
          AND er.seen_at > $2
          AND (e.kind = ANY($3) OR e.tagvalues @> ARRAY['r'])
        ORDER BY er.seen_at ASC
        LIMIT $4
        """,
        relay_url,
        last_seen_at,
        kinds,
        limit,
    )
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Candidate Lifecycle
# ---------------------------------------------------------------------------


async def upsert_candidates(brotr: Brotr, relays: Iterable[Relay]) -> int:
    """Insert relays as validation candidates for the Validator service.

    Builds ``service_data`` records with ``service_name='validator'`` and
    ``data_type='candidate'``, then upserts them via Brotr.  Existing
    candidates (same URL) are updated with fresh timestamps.

    Args:
        brotr: Database interface for persistence.
        relays: Relay objects to register as candidates.

    Returns:
        Number of candidate records upserted.
    """
    now = int(time.time())
    records: list[tuple[str, str, str, dict[str, Any]]] = [
        (
            ServiceName.VALIDATOR,
            DataType.CANDIDATE,
            relay.url,
            {"failed_attempts": 0, "network": relay.network.value, "inserted_at": now},
        )
        for relay in relays
    ]
    if records:
        await brotr.upsert_service_data(records)
    return len(records)


async def count_candidates(
    brotr: Brotr, networks: list[str], *, timeout: float | None = None
) -> int:
    """Count pending validation candidates for the given networks.

    Args:
        brotr: Database interface.
        networks: Network type strings (e.g. ``['clearnet', 'tor']``).
        timeout: Query timeout override.

    Returns:
        Total count of matching candidates.
    """
    row = await brotr.fetchrow(
        """
        SELECT COUNT(*)::int AS count
        FROM service_data
        WHERE service_name = $1
          AND data_type = $2
          AND data->>'network' = ANY($3)
        """,
        ServiceName.VALIDATOR,
        DataType.CANDIDATE,
        networks,
        timeout=timeout,
    )
    return row["count"] if row else 0


async def fetch_candidate_chunk(
    brotr: Brotr,
    networks: list[str],
    before_timestamp: int,
    limit: int,
    *,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch candidates prioritized by fewest failures, then oldest.

    Only returns candidates updated before ``before_timestamp`` to avoid
    reprocessing within the same cycle.

    Args:
        brotr: Database interface.
        networks: Network type strings to include.
        before_timestamp: Exclude candidates updated after this time.
        limit: Maximum candidates to return.
        timeout: Query timeout override.

    Returns:
        List of dicts with keys: ``data_key``, ``data``.
    """
    rows = await brotr.fetch(
        """
        SELECT data_key, data
        FROM service_data
        WHERE service_name = $1
          AND data_type = $2
          AND data->>'network' = ANY($3)
          AND updated_at < $4
        ORDER BY COALESCE((data->>'failed_attempts')::int, 0) ASC,
                 updated_at ASC
        LIMIT $5
        """,
        ServiceName.VALIDATOR,
        DataType.CANDIDATE,
        networks,
        before_timestamp,
        limit,
        timeout=timeout,
    )
    return [dict(row) for row in rows]


async def delete_stale_candidates(brotr: Brotr, *, timeout: float | None = None) -> str:
    """Remove candidates whose URLs already exist in the relays table.

    Returns:
        PostgreSQL command status string (e.g. ``'DELETE 5'``).
    """
    return await brotr.execute(
        """
        DELETE FROM service_data
        WHERE service_name = $1
          AND data_type = $2
          AND EXISTS (SELECT 1 FROM relays r WHERE r.url = data_key)
        """,
        ServiceName.VALIDATOR,
        DataType.CANDIDATE,
        timeout=timeout,
    )


async def delete_exhausted_candidates(
    brotr: Brotr, max_failures: int, *, timeout: float | None = None
) -> str:
    """Remove candidates that have exceeded the failure threshold.

    Args:
        brotr: Database interface.
        max_failures: Maximum allowed failed attempts.
        timeout: Query timeout override.

    Returns:
        PostgreSQL command status string (e.g. ``'DELETE 3'``).
    """
    return await brotr.execute(
        """
        DELETE FROM service_data
        WHERE service_name = $1
          AND data_type = $2
          AND COALESCE((data->>'failed_attempts')::int, 0) >= $3
        """,
        ServiceName.VALIDATOR,
        DataType.CANDIDATE,
        max_failures,
        timeout=timeout,
    )


async def promote_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Atomically insert relays and remove their candidate records.

    Runs both operations in a single transaction to prevent orphaned
    candidates if the process crashes mid-promotion.

    Args:
        brotr: Database interface.
        relays: Validated relays to promote from candidates to relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ON CONFLICT).
    """
    if not relays:
        return 0

    params = [relay.to_db_params() for relay in relays]
    urls = [p.url for p in params]
    networks = [p.network for p in params]
    discovered_ats = [p.discovered_at for p in params]

    async with brotr.transaction() as conn:
        inserted = (
            await conn.fetchval(
                "SELECT relays_insert($1, $2, $3)",
                urls,
                networks,
                discovered_ats,
            )
            or 0
        )
        await conn.execute(
            """
            DELETE FROM service_data
            WHERE service_name = $1
              AND data_type = $2
              AND data_key = ANY($3::text[])
            """,
            ServiceName.VALIDATOR,
            DataType.CANDIDATE,
            urls,
        )

    return inserted


# ---------------------------------------------------------------------------
# Cursor Queries
# ---------------------------------------------------------------------------


async def get_all_service_cursors(
    brotr: Brotr,
    service_name: str,
    cursor_field: str = "last_synced_at",
) -> dict[str, int]:
    """Batch-fetch all cursor positions for a service.

    Args:
        brotr: Database interface.
        service_name: Service owning the cursors.
        cursor_field: JSON key containing the cursor value.

    Returns:
        Dict mapping data_key (relay URL) to cursor value (timestamp).
    """
    rows = await brotr.fetch(
        """
        SELECT data_key, (data->>$1)::BIGINT as cursor_value
        FROM service_data
        WHERE service_name = $2 AND data_type = $3
        """,
        cursor_field,
        service_name,
        DataType.CURSOR,
    )
    return {r["data_key"]: r["cursor_value"] for r in rows if r["cursor_value"] is not None}
