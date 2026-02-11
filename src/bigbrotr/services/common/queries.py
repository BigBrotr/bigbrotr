"""Domain-specific database queries for BigBrotr services.

All SQL queries used by services are centralized here.  Each function
accepts a [Brotr][bigbrotr.core.brotr.Brotr] instance and returns typed
results.  Services import from this module instead of writing inline SQL.

The 13 query functions are grouped into four categories:

- **Relay queries**: ``get_all_relay_urls``, ``get_all_relays``,
  ``filter_new_relay_urls``
- **Check / monitoring queries**: ``count_relays_due_for_check``,
  ``fetch_relays_due_for_check``
- **Event queries**: ``get_events_with_relay_urls``
- **Candidate lifecycle**: ``upsert_candidates``, ``count_candidates``,
  ``fetch_candidate_chunk``, ``delete_stale_candidates``,
  ``delete_exhausted_candidates``, ``promote_candidates``
- **Cursor queries**: ``get_all_service_cursors``

Warning:
    All queries run with the default or caller-supplied ``timeout``. Long-
    running queries (especially ``fetch_relays_due_for_check`` and
    ``get_events_with_relay_urls``) should use the
    ``brotr.config.timeouts.query`` setting to avoid blocking the event
    loop indefinitely. Consider setting a ``statement_timeout`` at the
    PostgreSQL connection level as a safety net.

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade that provides
        ``fetch()``, ``fetchrow()``, ``fetchval()``, ``execute()``,
        and ``transaction()`` methods used by every query function.
    [ServiceState][bigbrotr.models.service_state.ServiceState]: Dataclass
        used for candidate and cursor records in ``service_state``.
"""

from __future__ import annotations

import time
from collections.abc import Iterable  # noqa: TC003
from typing import TYPE_CHECKING, Any

from .constants import ServiceName, ServiceState, StateType


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.relay import Relay


# ---------------------------------------------------------------------------
# Relay Queries
# ---------------------------------------------------------------------------


async def get_all_relay_urls(brotr: Brotr) -> list[str]:
    """Fetch all relay URLs from the database, ordered alphabetically.

    Called by [Finder][bigbrotr.services.finder.Finder] at the start of
    event-scanning relay discovery to determine which relays to scan.

    See Also:
        [get_all_relays][bigbrotr.services.common.queries.get_all_relays]:
            Similar query that also returns ``network`` and
            ``discovered_at``.
    """
    rows = await brotr.fetch("SELECT url FROM relay ORDER BY url")
    return [row["url"] for row in rows]


async def get_all_relays(brotr: Brotr) -> list[dict[str, Any]]:
    """Fetch all relays with their network and discovery timestamp.

    Called by [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]
    to build the list of relays for event collection.

    Returns:
        List of dicts with keys: ``url``, ``network``, ``discovered_at``.

    See Also:
        [get_all_relay_urls][bigbrotr.services.common.queries.get_all_relay_urls]:
            Lightweight variant returning only URLs.
    """
    rows = await brotr.fetch(
        """
        SELECT url, network, discovered_at
        FROM relay
        ORDER BY discovered_at ASC
        """
    )
    return [dict(row) for row in rows]


async def filter_new_relay_urls(
    brotr: Brotr,
    urls: list[str],
    *,
    timeout: float | None = None,  # noqa: ASYNC109
) -> list[str]:
    """Filter URLs to those not already in relays or validator candidates.

    Called by [Seeder][bigbrotr.services.seeder.Seeder] to avoid inserting
    duplicate seed URLs that already exist as relays or as pending
    validation candidates in ``service_state``.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        urls: Candidate URLs to check.
        timeout: Query timeout override.

    Returns:
        URLs that are genuinely new (not in relays, not in candidates).

    See Also:
        [upsert_candidates][bigbrotr.services.common.queries.upsert_candidates]:
            Typically called after filtering to insert the new URLs.
    """
    rows = await brotr.fetch(
        """
        SELECT url FROM unnest($1::text[]) AS url
        WHERE NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = url)
          AND NOT EXISTS (
              SELECT 1 FROM service_state ss
              WHERE ss.service_name = $2 AND ss.state_type = $3
                AND ss.state_key = url
          )
        """,
        urls,
        ServiceName.VALIDATOR,
        StateType.CANDIDATE,
        timeout=timeout,
    )
    return [row["url"] for row in rows]


# ---------------------------------------------------------------------------
# Check / Monitoring Queries
# ---------------------------------------------------------------------------

# Shared FROM/JOIN/WHERE for relay check queries (count + fetch).
# Parameters: $1=service_name, $2=state_type, $3=networks, $4=threshold
_RELAYS_DUE_FOR_CHECK_BASE = """
    FROM relay r
    LEFT JOIN service_state ss ON
        ss.service_name = $1
        AND ss.state_type = $2
        AND ss.state_key = r.url
    WHERE
        r.network = ANY($3)
        AND (ss.state_key IS NULL OR (ss.payload->>'last_check_at')::BIGINT < $4)
"""


async def count_relays_due_for_check(
    brotr: Brotr,
    service_name: str,
    threshold: int,
    networks: list[str],
    *,
    timeout: float | None = None,  # noqa: ASYNC109
) -> int:
    """Count relays needing health checks.

    Called by [Monitor][bigbrotr.services.monitor.Monitor] at the start of
    each cycle to populate
    ``BatchProgress.total``.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service requesting checks (e.g.,
            ``ServiceName.MONITOR``).
        threshold: Unix timestamp cutoff -- relays last checked before this
            are considered due.
        networks: Network type strings to include.
        timeout: Query timeout override.

    Returns:
        Number of relays due for a check.

    See Also:
        [fetch_relays_due_for_check][bigbrotr.services.common.queries.fetch_relays_due_for_check]:
            Companion function that fetches the actual relay rows.
    """
    row = await brotr.fetchrow(
        f"SELECT COUNT(*)::int AS count {_RELAYS_DUE_FOR_CHECK_BASE}",
        service_name,
        StateType.CHECKPOINT,
        networks,
        threshold,
        timeout=timeout,
    )
    return row["count"] if row else 0


async def fetch_relays_due_for_check(  # noqa: PLR0913
    brotr: Brotr,
    service_name: str,
    threshold: int,
    networks: list[str],
    limit: int,
    *,
    timeout: float | None = None,  # noqa: ASYNC109
) -> list[dict[str, Any]]:
    """Fetch relays due for health checks, ordered by least-recently-checked.

    Called by [Monitor][bigbrotr.services.monitor.Monitor] during chunk-based
    processing to retrieve the next batch of relays needing health checks.
    Ordering ensures that relays with the oldest (or missing) checkpoint
    are checked first.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service requesting checks (e.g.,
            ``ServiceName.MONITOR``).
        threshold: Unix timestamp cutoff -- relays last checked before this
            are considered due.
        networks: Network type strings to include.
        limit: Maximum relays to return.
        timeout: Query timeout override.

    Returns:
        List of dicts with keys: ``url``, ``network``, ``discovered_at``.

    See Also:
        [count_relays_due_for_check][bigbrotr.services.common.queries.count_relays_due_for_check]:
            Companion count query sharing the same base SQL.
    """
    rows = await brotr.fetch(
        f"""
        SELECT r.url, r.network, r.discovered_at
        {_RELAYS_DUE_FOR_CHECK_BASE}
        ORDER BY
            COALESCE((ss.payload->>'last_check_at')::BIGINT, 0) ASC,
            r.discovered_at ASC
        LIMIT $5
        """,
        service_name,
        StateType.CHECKPOINT,
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
    ``r`` tags, cursor-paginated by ``seen_at``. The cursor is stored per
    relay in ``service_state`` so that historical events inserted by
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] are
    eventually processed.

    Called by [Finder][bigbrotr.services.finder.Finder] during per-relay
    event scanning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relay_url: Source relay to scan events from.
        last_seen_at: Cursor position -- only events seen after this.
        kinds: Event kinds to include (e.g. contact lists, relay lists).
        limit: Maximum events per batch.

    Returns:
        List of event dicts with keys: ``id``, ``created_at``, ``kind``,
        ``tags``, ``content``, ``seen_at``.

    Warning:
        This query joins ``event`` with ``event_relay`` and filters on
        ``tagvalues``, which can be expensive on large tables. Always pass
        an appropriate ``limit`` and ensure indexes exist on
        ``event_relay(relay_url, seen_at)`` and ``event(tagvalues)``.

    See Also:
        [get_all_service_cursors][bigbrotr.services.common.queries.get_all_service_cursors]:
            Batch-fetches the per-relay cursor values used as
            ``last_seen_at``.
    """
    rows = await brotr.fetch(
        """
        SELECT e.id, e.created_at, e.kind, e.tags, e.content, er.seen_at
        FROM event e
        INNER JOIN event_relay er ON e.id = er.event_id
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

    Builds [ServiceState][bigbrotr.models.service_state.ServiceState]
    records with ``service_name='validator'`` and
    ``state_type='candidate'``, then upserts them via
    [Brotr][bigbrotr.core.brotr.Brotr].  Existing candidates (same URL)
    are updated with fresh timestamps.

    Called by [Seeder][bigbrotr.services.seeder.Seeder] and
    [Finder][bigbrotr.services.finder.Finder] to register newly
    discovered relay URLs for validation.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface
            for persistence.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to register
            as candidates.

    Returns:
        Number of candidate records upserted.

    See Also:
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
            Moves validated candidates from ``service_state`` to the
            ``relay`` table.
        [fetch_candidate_chunk][bigbrotr.services.common.queries.fetch_candidate_chunk]:
            Retrieves candidates for validation processing.
    """
    now = int(time.time())
    records: list[ServiceState] = [
        ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=StateType.CANDIDATE,
            state_key=relay.url,
            payload={"failed_attempts": 0, "network": relay.network.value, "inserted_at": now},
            updated_at=now,
        )
        for relay in relays
    ]
    if records:
        await brotr.upsert_service_state(records)
    return len(records)


async def count_candidates(
    brotr: Brotr,
    networks: list[str],
    *,
    timeout: float | None = None,  # noqa: ASYNC109
) -> int:
    """Count pending validation candidates for the given networks.

    Called by [Validator][bigbrotr.services.validator.Validator] at the
    start of each cycle to populate
    ``BatchProgress.total``.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network type strings (e.g. ``['clearnet', 'tor']``).
        timeout: Query timeout override.

    Returns:
        Total count of matching candidates.

    See Also:
        [fetch_candidate_chunk][bigbrotr.services.common.queries.fetch_candidate_chunk]:
            Fetches the actual candidate rows for processing.
    """
    row = await brotr.fetchrow(
        """
        SELECT COUNT(*)::int AS count
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND payload->>'network' = ANY($3)
        """,
        ServiceName.VALIDATOR,
        StateType.CANDIDATE,
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
    timeout: float | None = None,  # noqa: ASYNC109
) -> list[dict[str, Any]]:
    """Fetch candidates prioritized by fewest failures, then oldest.

    Only returns candidates updated before ``before_timestamp`` to avoid
    reprocessing within the same cycle.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    chunk-based processing. The ordering ensures candidates most likely
    to succeed (fewest prior failures) are validated first.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network type strings to include.
        before_timestamp: Exclude candidates updated after this time.
        limit: Maximum candidates to return.
        timeout: Query timeout override.

    Returns:
        List of dicts with keys: ``state_key``, ``payload``.

    See Also:
        [count_candidates][bigbrotr.services.common.queries.count_candidates]:
            Companion count query.
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
            Called after successful validation to move candidates to
            the ``relay`` table.
    """
    rows = await brotr.fetch(
        """
        SELECT state_key, payload
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND payload->>'network' = ANY($3)
          AND updated_at < $4
        ORDER BY COALESCE((payload->>'failed_attempts')::int, 0) ASC,
                 updated_at ASC
        LIMIT $5
        """,
        ServiceName.VALIDATOR,
        StateType.CANDIDATE,
        networks,
        before_timestamp,
        limit,
        timeout=timeout,
    )
    return [dict(row) for row in rows]


async def delete_stale_candidates(brotr: Brotr, *, timeout: float | None = None) -> str:  # noqa: ASYNC109
    """Remove candidates whose URLs already exist in the relays table.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    cleanup at the start of each cycle. Stale candidates appear when a
    relay was validated by another cycle, manually added, or re-discovered
    by [Finder][bigbrotr.services.finder.Finder].

    Returns:
        PostgreSQL command status string (e.g. ``'DELETE 5'``).

    See Also:
        [delete_exhausted_candidates][bigbrotr.services.common.queries.delete_exhausted_candidates]:
            Companion cleanup that removes permanently failing candidates.
    """
    return await brotr.execute(
        """
        DELETE FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
        """,
        ServiceName.VALIDATOR,
        StateType.CANDIDATE,
        timeout=timeout,
    )


async def delete_exhausted_candidates(
    brotr: Brotr,
    max_failures: int,
    *,
    timeout: float | None = None,  # noqa: ASYNC109
) -> str:
    """Remove candidates that have exceeded the failure threshold.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    cleanup when ``cleanup.enabled`` is ``True``. Prevents permanently
    broken relays from consuming validation resources indefinitely.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        max_failures: Maximum allowed failed attempts (from
            ``cleanup.max_failures`` in
            [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]).
        timeout: Query timeout override.

    Returns:
        PostgreSQL command status string (e.g. ``'DELETE 3'``).

    See Also:
        [delete_stale_candidates][bigbrotr.services.common.queries.delete_stale_candidates]:
            Companion cleanup that removes already-promoted candidates.
    """
    return await brotr.execute(
        """
        DELETE FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND COALESCE((payload->>'failed_attempts')::int, 0) >= $3
        """,
        ServiceName.VALIDATOR,
        StateType.CANDIDATE,
        max_failures,
        timeout=timeout,
    )


async def promote_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Atomically insert relays and remove their candidate records.

    Runs both operations in a single
    [Brotr.transaction()][bigbrotr.core.brotr.Brotr.transaction] to
    prevent orphaned candidates if the process crashes mid-promotion.

    Called by [Validator][bigbrotr.services.validator.Validator] after
    successful WebSocket validation to move candidates into the ``relay``
    table.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: Validated [Relay][bigbrotr.models.relay.Relay] objects to
            promote from candidates to the relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ``ON CONFLICT``).

    Note:
        Uses the ``relay_insert`` stored procedure for bulk insertion.
        The transaction ensures atomicity: if the insert succeeds but
        the delete fails, neither operation is committed.

    See Also:
        [upsert_candidates][bigbrotr.services.common.queries.upsert_candidates]:
            The inverse operation that creates candidate records.
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
                "SELECT relay_insert($1, $2, $3)",
                urls,
                networks,
                discovered_ats,
            )
            or 0
        )
        await conn.execute(
            """
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND state_key = ANY($3::text[])
            """,
            ServiceName.VALIDATOR,
            StateType.CANDIDATE,
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

    Called by [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]
    and [Finder][bigbrotr.services.finder.Finder] to pre-fetch all per-relay
    cursor values in a single query, avoiding the N+1 pattern of
    fetching one cursor per relay.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service owning the cursors (e.g.,
            ``ServiceName.SYNCHRONIZER``).
        cursor_field: JSON key in ``payload`` containing the cursor value
            (e.g., ``"last_synced_at"`` or ``"last_seen_at"``).

    Returns:
        Dict mapping ``state_key`` (relay URL) to cursor value (timestamp).

    Note:
        Rows where the cursor field is ``NULL`` or missing are silently
        excluded from the result.

    See Also:
        [StateType.CURSOR][bigbrotr.models.service_state.StateType]:
            The ``state_type`` filter used in this query.
    """
    rows = await brotr.fetch(
        """
        SELECT state_key, (payload->>$1)::BIGINT as cursor_value
        FROM service_state
        WHERE service_name = $2 AND state_type = $3
        """,
        cursor_field,
        service_name,
        StateType.CURSOR,
    )
    return {r["state_key"]: r["cursor_value"] for r in rows if r["cursor_value"] is not None}
