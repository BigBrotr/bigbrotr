"""Domain-specific database queries for BigBrotr services.

All SQL queries used by services are centralized here.  Each function
accepts a [Brotr][bigbrotr.core.brotr.Brotr] instance and returns typed
results.  Services import from this module instead of writing inline SQL.

Batch-insert wrappers split large inputs into chunks of
``BatchConfig.max_size`` so that services never need to manage Brotr's
batch limit directly.

The 14 query functions are grouped into four categories:

- **Relay queries**: ``fetch_relays``, ``fetch_relays_to_monitor``,
  ``insert_relays``, ``insert_relay_metadata``
- **Event queries**: ``scan_event_relay``, ``scan_event``,
  ``insert_event_relays``
- **Candidate lifecycle**: ``insert_relays_as_candidates``,
  ``count_candidates``, ``fetch_candidates``, ``promote_candidates``,
  ``upsert_service_states``
- **Cleanup**: ``delete_exhausted_candidates``, ``cleanup_stale``

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
from typing import TYPE_CHECKING, Any, TypeVar

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.relay import Relay
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .types import Candidate, EventCursor, EventRelayCursor


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.event_relay import EventRelay
    from bigbrotr.models.relay_metadata import RelayMetadata

_T = TypeVar("_T")

logger = logging.getLogger(__name__)


# =============================================================================
# Private helpers
# =============================================================================


async def _fetch_relays(brotr: Brotr, query: str, *args: Any) -> list[Relay]:
    """Execute *query* via ``brotr.fetch`` and construct Relay objects from the rows.

    Shared implementation for :func:`fetch_relays` and
    :func:`fetch_relays_to_monitor`.  Rows that fail ``Relay``
    construction (invalid URL) are silently skipped.
    """
    rows = await brotr.fetch(query, *args)
    relays: list[Relay] = []
    for row in rows:
        try:
            relays.append(Relay(row["url"], row["discovered_at"]))
        except (ValueError, TypeError) as e:
            logger.warning("Skipping invalid relay URL %s: %s", row["url"], e)
    return relays


async def _batched_insert(
    brotr: Brotr,
    records: list[_T],
    method: Callable[[list[_T]], Awaitable[int]],
) -> int:
    """Split *records* into batches of ``brotr.config.batch.max_size`` and
    call *method* on each chunk, returning the total count."""
    if not records:
        return 0
    total = 0
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        total += await method(records[i : i + batch_size])
    return total


async def _filter_new_relays(
    brotr: Brotr,
    relays: list[Relay],
) -> list[Relay]:
    """Keep only relays not already in the database or pending validation."""
    urls = [r.url for r in relays]
    if not urls:
        return []

    rows = await brotr.fetch(
        """
        SELECT t.url FROM unnest($1::text[]) AS t(url)
        WHERE NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = t.url)
          AND NOT EXISTS (
              SELECT 1 FROM service_state ss
              WHERE ss.service_name = $2 AND ss.state_type = $3
                AND ss.state_key = t.url
          )
        """,
        urls,
        ServiceName.VALIDATOR,
        ServiceStateType.CANDIDATE,
    )
    new_urls = {row["url"] for row in rows}
    return [r for r in relays if r.url in new_urls]


# =============================================================================
# Relay queries
# =============================================================================


async def fetch_relays(brotr: Brotr) -> list[Relay]:
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
        ServiceStateType.CHECKPOINT,
    )


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
        [insert_relays_as_candidates][bigbrotr.services.common.queries.insert_relays_as_candidates]:
            Alternative that inserts as validation candidates instead.
    """
    return await _batched_insert(brotr, relays, brotr.insert_relay)


async def insert_relay_metadata(brotr: Brotr, records: list[RelayMetadata]) -> int:
    """Batch-insert relay-metadata junction records.

    Splits *records* into batches respecting
    [BatchConfig.max_size][bigbrotr.core.brotr.BatchConfig] and delegates
    each chunk to
    [Brotr.insert_relay_metadata()][bigbrotr.core.brotr.Brotr.insert_relay_metadata]
    (cascade mode).

    Called by [Monitor][bigbrotr.services.monitor.Monitor] to persist
    health-check metadata.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        records: [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
            instances to insert.

    Returns:
        Number of new relay-metadata records inserted.
    """
    return await _batched_insert(brotr, records, brotr.insert_relay_metadata)


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

    Called by [Finder][bigbrotr.services.finder.Finder] at the start of
    each event-scanning cycle.

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
                logger.warning("Skipping invalid cursor for %s", url)
                cursors.append(EventRelayCursor(relay_url=url))
        else:
            cursors.append(EventRelayCursor(relay_url=url))
    return cursors


# =============================================================================
# Event queries
# =============================================================================


async def scan_event_relay(
    brotr: Brotr,
    cursor: EventRelayCursor,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan event-relay rows for a specific relay, cursor-paginated.

    Uses a composite cursor ``(seen_at, event_id)`` for deterministic
    pagination that handles ties in ``seen_at``. When the cursor has
    ``seen_at=None`` (new cursor), scanning starts from the beginning.

    Called by [Finder][bigbrotr.services.finder.Finder] during per-relay
    event scanning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        cursor: [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
            with relay URL and pagination position.
        limit: Maximum rows per batch.

    Returns:
        List of dicts with all event columns plus ``seen_at`` from the
        ``event_relay`` junction.

    See Also:
        [scan_event][bigbrotr.services.common.queries.scan_event]:
            Analogous scan over the ``event`` table.
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


async def scan_event(
    brotr: Brotr,
    cursor: EventCursor,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan event rows ordered by creation time, cursor-paginated.

    Uses a composite cursor ``(created_at, event_id)`` for deterministic
    pagination that handles ties in ``created_at``. When the cursor has
    ``created_at=None`` (new cursor), scanning starts from the beginning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        cursor: [EventCursor][bigbrotr.services.common.types.EventCursor]
            with pagination position.
        limit: Maximum rows per batch.

    Returns:
        List of dicts with all event columns.

    See Also:
        [scan_event_relay][bigbrotr.services.common.queries.scan_event_relay]:
            Analogous scan over the ``event_relay`` junction.
    """
    rows = await brotr.fetch(
        """
        SELECT id, pubkey, created_at, kind, tags, tagvalues, content, sig
        FROM event
        WHERE ($1::bigint IS NULL OR (created_at, id) > ($1::bigint, $2::bytea))
        ORDER BY created_at ASC, id ASC
        LIMIT $3
        """,
        cursor.created_at,
        cursor.event_id,
        limit,
    )
    return [dict(row) for row in rows]


async def insert_event_relays(brotr: Brotr, records: list[EventRelay]) -> int:
    """Batch-insert event-relay junction records.

    Splits *records* into batches respecting
    [BatchConfig.max_size][bigbrotr.core.brotr.BatchConfig] and delegates
    each chunk to
    [Brotr.insert_event_relay()][bigbrotr.core.brotr.Brotr.insert_event_relay]
    (cascade mode).

    Called by
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] to
    persist ingested events.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        records: [EventRelay][bigbrotr.models.event_relay.EventRelay]
            instances to insert.

    Returns:
        Number of new event-relay records inserted.
    """
    return await _batched_insert(brotr, records, brotr.insert_event_relay)


# =============================================================================
# Candidate lifecycle
# =============================================================================


async def insert_relays_as_candidates(brotr: Brotr, relays: list[Relay]) -> int:
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
    new_relays = await _filter_new_relays(brotr, relays)
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
    return await _batched_insert(brotr, records, brotr.upsert_service_state)


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
    updated_before: int,
    limit: int,
) -> list[Candidate]:
    """Fetch candidates prioritized by fewest failures, then oldest.

    Only returns candidates whose ``updated_at`` is before
    ``updated_before`` to avoid reprocessing within the same cycle.

    Called by [Validator][bigbrotr.services.validator.Validator] during
    chunk-based processing. The ordering ensures candidates most likely
    to succeed (fewest prior failures) are validated first.

    Rows whose ``state_key`` is not a valid relay URL are skipped
    with a warning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network types to include.
        updated_before: Exclude candidates updated after this Unix timestamp.
        limit: Maximum candidates to return.

    Returns:
        List of [Candidate][bigbrotr.services.common.types.Candidate]
        instances.

    See Also:
        [count_candidates][bigbrotr.services.common.queries.count_candidates]:
            Companion count query.
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
            Called after successful validation to move candidates to
            the ``relay`` table.
    """
    rows = await brotr.fetch(
        """
        SELECT state_key, state_value
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
        updated_before,
        limit,
    )
    candidates: list[Candidate] = []
    for row in rows:
        try:
            candidates.append(Candidate(relay=Relay(row["state_key"]), data=row["state_value"]))
        except (ValueError, TypeError) as e:
            logger.warning("Skipping invalid candidate URL %s: %s", row["state_key"], e)
    return candidates


async def promote_candidates(brotr: Brotr, candidates: list[Candidate]) -> int:
    """Insert relays and remove their candidate records.

    Called by [Validator][bigbrotr.services.validator.Validator] after
    successful WebSocket validation to move candidates into the ``relay``
    table. If the delete fails, orphaned candidates are cleaned up by
    ``cleanup_stale`` at the next cycle.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        candidates: Validated
            [Candidate][bigbrotr.services.common.types.Candidate] objects
            to promote from ``service_state`` to the relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ``ON CONFLICT``).

    See Also:
        [insert_relays_as_candidates][bigbrotr.services.common.queries.insert_relays_as_candidates]:
            The inverse operation that creates candidate records.
        [cleanup_stale][bigbrotr.services.common.queries.cleanup_stale]:
            Safety net that removes candidates already in the relay table.
    """
    if not candidates:
        return 0

    relays = [c.relay for c in candidates]
    inserted = await _batched_insert(brotr, relays, brotr.insert_relay)

    batch_size = brotr.config.batch.max_size
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i : i + batch_size]
        await brotr.delete_service_state(
            [ServiceName.VALIDATOR] * len(chunk),
            [ServiceStateType.CANDIDATE] * len(chunk),
            [c.relay.url for c in chunk],
        )
    return inserted


async def upsert_service_states(brotr: Brotr, records: list[ServiceState]) -> int:
    """Batch-upsert service state records.

    Splits *records* into batches respecting
    [BatchConfig.max_size][bigbrotr.core.brotr.BatchConfig] and delegates
    each chunk to
    [Brotr.upsert_service_state()][bigbrotr.core.brotr.Brotr.upsert_service_state].

    Services use this to persist operational state (cursors, monitoring
    markers, candidate failure counters) without worrying about batch
    size limits.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        records: [ServiceState][bigbrotr.models.service_state.ServiceState]
            instances to upsert.

    Returns:
        Number of records upserted.
    """
    return await _batched_insert(brotr, records, brotr.upsert_service_state)


# =============================================================================
# Cleanup
# =============================================================================


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
        [cleanup_stale][bigbrotr.services.common.queries.cleanup_stale]:
            Companion cleanup that removes stale candidates and state records.
    """
    # Direct DELETE (not via stored procedure) — cleanup query, already
    # centralised and parameterised; a procedure adds no benefit here.
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


async def cleanup_stale(
    brotr: Brotr,
    service_name: ServiceName,
) -> int:
    """Remove stale service state records for a given service.

    Iterates over all
    [ServiceStateType][bigbrotr.models.service_state.ServiceStateType]
    values and deletes rows that are no longer needed. The staleness
    condition depends on the state type:

    - **CANDIDATE**: stale when the relay *exists* in the ``relay``
      table (already promoted, so the candidate record is obsolete).
    - **CHECKPOINT / CURSOR**: stale when the relay URL does *not*
      exist in the ``relay`` table (orphaned after relay removal).
      Only targets URL-shaped keys (``state_key LIKE 'ws%'``) to
      protect non-URL keys like named checkpoints.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        service_name: Service whose stale records should be removed.

    Returns:
        Total number of stale rows deleted across all state types.

    See Also:
        [delete_exhausted_candidates][bigbrotr.services.common.queries.delete_exhausted_candidates]:
            Companion cleanup that removes candidates exceeding the failure
            threshold.
    """
    total = 0
    for state_type in ServiceStateType:
        if state_type == ServiceStateType.CANDIDATE:
            query = """
                WITH deleted AS (
                    DELETE FROM service_state ss
                    WHERE ss.service_name = $1
                      AND ss.state_type = $2
                      AND EXISTS (SELECT 1 FROM relay r WHERE r.url = ss.state_key)
                    RETURNING 1
                )
                SELECT count(*)::int FROM deleted
                """
        else:
            query = """
                WITH deleted AS (
                    DELETE FROM service_state ss
                    WHERE ss.service_name = $1
                      AND ss.state_type = $2
                      AND ss.state_key LIKE 'ws%'
                      AND NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = ss.state_key)
                    RETURNING 1
                )
                SELECT count(*)::int FROM deleted
                """

        count: int | None = await brotr.fetchval(query, service_name, state_type)
        total += count or 0

    return total
