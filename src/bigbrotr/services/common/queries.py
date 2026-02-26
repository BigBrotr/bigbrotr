"""Domain-specific database queries for BigBrotr services.

All SQL queries used by services are centralized here.  Each function
accepts a [Brotr][bigbrotr.core.brotr.Brotr] instance and returns typed
results.  Services import from this module instead of writing inline SQL.

The 13 query functions are grouped into five categories:

- **Relay queries**: ``fetch_all_relays``, ``filter_new_relays``,
  ``insert_relays``
- **Monitoring queries**: ``fetch_relays_to_monitor``
- **Event queries**: ``fetch_event_tagvalues``
- **Candidate lifecycle**: ``insert_candidates``, ``count_candidates``,
  ``fetch_candidates``, ``delete_stale_candidates``,
  ``delete_exhausted_candidates``, ``promote_candidates``
- **Cursor queries**: ``get_all_cursor_values``, ``delete_orphan_cursors``

Warning:
    All queries use the timeout from
    [TimeoutsConfig][bigbrotr.core.brotr.TimeoutsConfig]
    (``timeouts.query`` for reads, ``timeouts.batch`` for writes).
    The PostgreSQL ``statement_timeout`` acts as a server-side safety net.

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade that provides
        ``fetch()``, ``fetchrow()``, ``fetchval()``, ``execute()``,
        and ``transaction()`` methods used by every query function.
    [ServiceState][bigbrotr.models.service_state.ServiceState]: Dataclass
        used for candidate and cursor records in ``service_state``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.relay import Relay, RelayDbParams
from bigbrotr.models.service_state import ServiceState, ServiceStateType


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr

logger = logging.getLogger(__name__)


# =============================================================================
# Private helpers
# =============================================================================


async def _fetch_relays(brotr: Brotr, query: str, *args: Any) -> list[Relay]:
    """Execute *query* via ``brotr.fetch`` and construct Relay objects from the rows.

    Shared implementation for :func:`fetch_all_relays` and
    :func:`fetch_relays_to_monitor`.  Rows that fail ``Relay``
    construction (invalid URL) are silently skipped.
    """
    rows = await brotr.fetch(query, *args)
    relays: list[Relay] = []
    for row in rows:
        try:
            params = RelayDbParams(row["url"], row["network"], row["discovered_at"])
            relays.append(Relay.from_db_params(params))
        except (ValueError, TypeError) as e:
            logger.debug("Skipping invalid relay URL %s: %s", row["url"], e)
    return relays


async def _fetch_service_states(brotr: Brotr, query: str, *args: Any) -> list[ServiceState]:
    """Execute *query* via ``brotr.fetch`` and construct ServiceState objects.

    Shared implementation for service_state fetch queries.  Rows that fail
    ``ServiceState`` construction are silently skipped.
    """
    rows = await brotr.fetch(query, *args)
    states: list[ServiceState] = []
    for row in rows:
        try:
            states.append(
                ServiceState(
                    service_name=row["service_name"],
                    state_type=row["state_type"],
                    state_key=row["state_key"],
                    state_value=row["state_value"],
                    updated_at=row["updated_at"],
                )
            )
        except (ValueError, TypeError) as e:
            logger.debug("Skipping invalid service state %s: %s", row["state_key"], e)
    return states


# =============================================================================
# Relay queries
# =============================================================================


async def fetch_all_relays(brotr: Brotr) -> list[Relay]:
    """Fetch all relays from the database as domain objects.

    Called by [Finder][bigbrotr.services.finder.Finder] and
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer].
    Rows that fail ``Relay`` construction (invalid URL) are silently
    skipped.

    Returns:
        List of [Relay][bigbrotr.models.relay.Relay] instances ordered
        by ``discovered_at`` ascending.
    """
    return await _fetch_relays(
        brotr,
        """
        SELECT url, network, discovered_at
        FROM relay
        ORDER BY discovered_at ASC
        """,
    )


async def filter_new_relays(
    brotr: Brotr,
    relays: list[Relay],
) -> list[Relay]:
    """Keep only relays not already in the database or pending validation.

    Queries the ``relay`` table and ``service_state`` candidates to
    determine which of the given relays are genuinely new.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to check.

    Returns:
        Relays whose URL is not yet known (not in relays, not in candidates).

    See Also:
        [insert_candidates][bigbrotr.services.common.queries.insert_candidates]:
            Uses this function internally to skip known relays.
    """
    urls = [r.url for r in relays]
    if not urls:
        return []

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
        ServiceStateType.CANDIDATE,
    )
    new_urls = {row["url"] for row in rows}
    return [r for r in relays if r.url in new_urls]


async def insert_relays(brotr: Brotr, relays: list[Relay]) -> int:
    """Bulk-insert relays directly into the ``relay`` table.

    Respects the configured batch size from
    [BatchConfig][bigbrotr.core.brotr.BatchConfig], splitting large inputs
    into multiple ``insert_relay`` calls. Duplicates are silently skipped
    (``ON CONFLICT DO NOTHING``).

    Called by [Seeder][bigbrotr.services.seeder.Seeder] when
    ``to_validate=False`` to bypass validation.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to insert.

    Returns:
        Number of relays actually inserted.

    See Also:
        [insert_candidates][bigbrotr.services.common.queries.insert_candidates]:
            Alternative that inserts as validation candidates instead.
    """
    if not relays:
        return 0

    inserted = 0
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(relays), batch_size):
        inserted += await brotr.insert_relay(relays[i : i + batch_size])
    return inserted


# =============================================================================
# Monitoring queries
# =============================================================================


async def fetch_relays_to_monitor(
    brotr: Brotr,
    monitored_before: int,
    networks: list[NetworkType],
) -> list[Relay]:
    """Fetch relays due for monitoring, ordered by least-recently-monitored.

    Returns relays that have never been monitored or whose last monitoring
    occurred before ``monitored_before``.  Ordering ensures that relays
    with the oldest (or missing) monitoring marker are monitored first.
    Rows that fail ``Relay`` construction are skipped.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        monitored_before: Exclusive upper bound -- only relays whose
            ``monitored_at`` is before this Unix timestamp (or NULL)
            are returned.
        networks: Network types to include.

    Returns:
        List of [Relay][bigbrotr.models.relay.Relay] instances.
    """
    return await _fetch_relays(
        brotr,
        """
        SELECT r.url, r.network, r.discovered_at
        FROM relay r
        LEFT JOIN service_state ss ON
            ss.service_name = $3
            AND ss.state_type = $4
            AND ss.state_key = r.url
        WHERE
            r.network = ANY($1)
            AND (ss.state_key IS NULL
                 OR (ss.state_value->>'monitored_at')::BIGINT < $2)
        ORDER BY
            COALESCE((ss.state_value->>'monitored_at')::BIGINT, 0) ASC,
            r.discovered_at ASC
        """,
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.MONITORING,
    )


# =============================================================================
# Event queries
# =============================================================================


async def fetch_event_tagvalues(
    brotr: Brotr,
    relay_url: str,
    cursor_seen_at: int | None,
    cursor_event_id: bytes | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch event tagvalues from a specific relay, cursor-paginated.

    Uses a composite cursor ``(seen_at, event_id)`` for deterministic
    pagination that handles ties in ``seen_at``. When both cursor
    components are ``None`` (new cursor), all events are returned.

    Called by [Finder][bigbrotr.services.finder.Finder] during per-relay
    event scanning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relay_url: Source relay to scan events from.
        cursor_seen_at: ``seen_at`` from the last processed row, or
            ``None`` to start from the beginning.
        cursor_event_id: ``event_id`` (raw bytes) from the last processed
            row, or ``None`` to start from the beginning.
        limit: Maximum events per batch.

    Returns:
        List of dicts with keys: ``tagvalues`` (``list[str]``),
        ``seen_at`` (``int``), ``event_id`` (``bytes``).

    See Also:
        [get_all_cursor_values][bigbrotr.services.common.queries.get_all_cursor_values]:
            Batch-fetches the per-relay cursor state used to supply
            ``cursor_seen_at`` and ``cursor_event_id``.
    """
    rows = await brotr.fetch(
        """
        SELECT e.tagvalues, er.seen_at, e.id AS event_id
        FROM event e
        INNER JOIN event_relay er ON e.id = er.event_id
        WHERE er.relay_url = $1
          AND ($2::bigint IS NULL OR (er.seen_at, e.id) > ($2::bigint, $3::bytea))
        ORDER BY er.seen_at ASC, e.id ASC
        LIMIT $4
        """,
        relay_url,
        cursor_seen_at,
        cursor_event_id,
        limit,
    )
    return [dict(row) for row in rows]


# =============================================================================
# Candidate lifecycle
# =============================================================================


async def insert_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Insert new validation candidates, skipping known relays and duplicates.

    Filters out URLs that already exist in the ``relay`` table or as
    pending candidates in ``service_state``, then persists only genuinely
    new records. Existing candidates retain their current state (e.g.
    ``failures`` counter is never reset).

    Called by [Seeder][bigbrotr.services.seeder.Seeder] and
    [Finder][bigbrotr.services.finder.Finder] to register newly
    discovered relay URLs for validation.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to register
            as candidates.

    Returns:
        Number of candidate records actually inserted.

    See Also:
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
            Moves validated candidates from ``service_state`` to the
            ``relay`` table.
        [fetch_candidates][bigbrotr.services.common.queries.fetch_candidates]:
            Retrieves candidates for validation processing.
    """
    new_relays = await filter_new_relays(brotr, relays)
    if not new_relays:
        return 0

    now = int(time.time())
    records: list[ServiceState] = [
        ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=ServiceStateType.CANDIDATE,
            state_key=relay.url,
            state_value={"failures": 0, "network": relay.network.value, "inserted_at": now},
            updated_at=now,
        )
        for relay in new_relays
    ]
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        await brotr.upsert_service_state(records[i : i + batch_size])
    return len(records)


async def count_candidates(
    brotr: Brotr,
    networks: list[NetworkType],
) -> int:
    """Count pending validation candidates for the given networks.

    Called by [Validator][bigbrotr.services.validator.Validator] at the
    start of each cycle to populate
    ``ChunkProgress.total``.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network types to include.

    Returns:
        Total count of matching candidates.

    See Also:
        [fetch_candidates][bigbrotr.services.common.queries.fetch_candidates]:
            Fetches the actual candidate rows for processing.
    """
    row = await brotr.fetchrow(
        """
        SELECT COUNT(*)::int AS count
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND state_value->>'network' = ANY($3)
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CANDIDATE,
        networks,
    )
    return row["count"] if row else 0


async def fetch_candidates(
    brotr: Brotr,
    networks: list[NetworkType],
    before_timestamp: int,
    limit: int,
) -> list[ServiceState]:
    """Fetch candidates prioritized by fewest failures, then oldest.

    Only returns candidates updated before ``before_timestamp`` to avoid
    reprocessing within the same cycle.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    chunk-based processing. The ordering ensures candidates most likely
    to succeed (fewest prior failures) are validated first.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network types to include.
        before_timestamp: Exclude candidates updated after this time.
        limit: Maximum candidates to return.

    Returns:
        List of [ServiceState][bigbrotr.models.service_state.ServiceState]
        instances.

    See Also:
        [count_candidates][bigbrotr.services.common.queries.count_candidates]:
            Companion count query.
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
            Called after successful validation to move candidates to
            the ``relay`` table.
    """
    return await _fetch_service_states(
        brotr,
        """
        SELECT service_name, state_type, state_key, state_value, updated_at
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND state_value->>'network' = ANY($3)
          AND updated_at < $4
        ORDER BY COALESCE((state_value->>'failures')::int, 0) ASC,
                 updated_at ASC
        LIMIT $5
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CANDIDATE,
        networks,
        before_timestamp,
        limit,
    )


async def delete_stale_candidates(brotr: Brotr) -> int:
    """Remove candidates whose URLs already exist in the relays table.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    cleanup at the start of each cycle. Stale candidates appear when a
    relay was validated by another cycle, manually added, or re-discovered
    by [Finder][bigbrotr.services.finder.Finder].

    Returns:
        Number of deleted rows.

    See Also:
        [delete_exhausted_candidates][bigbrotr.services.common.queries.delete_exhausted_candidates]:
            Companion cleanup that removes permanently failing candidates.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CANDIDATE,
    )
    return count


async def delete_exhausted_candidates(
    brotr: Brotr,
    max_failures: int,
) -> int:
    """Remove candidates that have exceeded the failure threshold.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    cleanup when ``cleanup.enabled`` is ``True``. Prevents permanently
    broken relays from consuming validation resources indefinitely.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        max_failures: Maximum allowed failed attempts (from
            ``cleanup.max_failures`` in
            [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]).

    Returns:
        Number of deleted rows.

    See Also:
        [delete_stale_candidates][bigbrotr.services.common.queries.delete_stale_candidates]:
            Companion cleanup that removes already-promoted candidates.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND COALESCE((state_value->>'failures')::int, 0) >= $3
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CANDIDATE,
        max_failures,
    )
    return count


async def promote_candidates(brotr: Brotr, relays: list[Relay]) -> int:
    """Insert relays and remove their candidate records.

    Called by [Validator][bigbrotr.services.validator.Validator] after
    successful WebSocket validation to move candidates into the ``relay``
    table. If the delete fails, orphaned candidates are cleaned up by
    ``delete_stale_candidates`` at the next cycle.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: Validated [Relay][bigbrotr.models.relay.Relay] objects to
            promote from candidates to the relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ``ON CONFLICT``).

    See Also:
        [insert_candidates][bigbrotr.services.common.queries.insert_candidates]:
            The inverse operation that creates candidate records.
        [delete_stale_candidates][bigbrotr.services.common.queries.delete_stale_candidates]:
            Safety net that removes candidates already in the relay table.
    """
    if not relays:
        return 0

    inserted = await brotr.insert_relay(relays)
    urls = [relay.url for relay in relays]
    await brotr.delete_service_state(
        [ServiceName.VALIDATOR] * len(relays),
        [ServiceStateType.CANDIDATE] * len(relays),
        urls,
    )
    return inserted


# =============================================================================
# Cursor queries
# =============================================================================


async def get_all_cursor_values(
    brotr: Brotr,
    service_name: ServiceName,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch all cursor state values for a service.

    Returns the full ``state_value`` dict for each cursor row so that
    each service can extract the fields it needs. The Finder uses a
    composite ``(seen_at, event_id)`` cursor; the Synchronizer uses a
    single ``last_synced_at`` timestamp.

    Called by [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]
    and [Finder][bigbrotr.services.finder.Finder] to pre-fetch all per-relay
    cursor values in a single query, avoiding the N+1 pattern of
    fetching one cursor per relay.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service owning the cursors (e.g.,
            ``ServiceName.SYNCHRONIZER``).

    Returns:
        Dict mapping ``state_key`` (relay URL) to the ``state_value``
        dict for that cursor row.

    See Also:
        [ServiceStateType.CURSOR][bigbrotr.models.service_state.ServiceStateType]:
            The ``state_type`` filter used in this query.
    """
    rows = await brotr.fetch(
        """
        SELECT state_key, state_value
        FROM service_state
        WHERE service_name = $1 AND state_type = $2
        """,
        service_name,
        ServiceStateType.CURSOR,
    )
    return {r["state_key"]: dict(r["state_value"]) for r in rows}


async def delete_orphan_cursors(brotr: Brotr, service_name: ServiceName) -> int:
    """Remove cursor records whose relay no longer exists in the ``relay`` table.

    Cursors accumulate indefinitely as relays are discovered and later removed.
    This cleanup prevents unbounded growth of stale cursor rows in
    ``service_state``.

    Called by [Finder][bigbrotr.services.finder.Finder] and
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] at the start
    of each cycle, before loading cursors.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service owning the cursors (e.g.,
            ``ServiceName.FINDER``).

    Returns:
        Number of orphan cursor rows deleted.

    See Also:
        [get_all_cursor_values][bigbrotr.services.common.queries.get_all_cursor_values]:
            The companion fetch query for cursor records.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND state_key NOT IN (SELECT url FROM relay)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        service_name,
        ServiceStateType.CURSOR,
    )
    return count
