"""Validator-specific database queries."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.relay import Relay
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.utils import batched_insert


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.services.common.types import CandidateCheckpoint


logger = logging.getLogger(__name__)

_CANDIDATE_NETWORKS = tuple(
    network.value
    for network in (
        NetworkType.CLEARNET,
        NetworkType.TOR,
        NetworkType.I2P,
        NetworkType.LOKI,
    )
)


async def delete_promoted_candidates(brotr: Brotr) -> int:
    """Remove candidates that have already been promoted to the relay table.

    Deletes CHECKPOINT records whose ``state_key`` matches a URL that now
    exists in the ``relay`` table.  Called during cleanup as a safety net
    for candidates that were validated but whose deletion after promotion
    failed.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        Number of deleted rows.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE owner = $1
              AND state_type = $2
              AND EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
    )
    return count


async def delete_exhausted_candidates(brotr: Brotr, max_failures: int) -> int:
    """Remove candidates that have exceeded the failure threshold.

    Deletes CHECKPOINT records whose ``failures`` counter meets or exceeds
    ``max_failures``. Called during cleanup when ``cleanup.enabled`` is
    ``True`` to prevent permanently broken relays from consuming validation
    resources indefinitely. Also removes malformed candidate rows whose
    persisted network or numeric fields can no longer be consumed by the
    validator runtime, so they do not block rediscovery of the same relay.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        max_failures: Failure threshold above which candidates are removed.

    Returns:
        Number of deleted rows.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE owner = $1
              AND state_type = $2
              AND (
                    jsonb_typeof(state_value->'failures') != 'number'
                    OR (state_value->>'failures') !~ '^[0-9]+$'
                    OR jsonb_typeof(state_value->'timestamp') != 'number'
                    OR (state_value->>'timestamp') !~ '^[0-9]+$'
                    OR COALESCE(state_value->>'network', '') != ALL($4::text[])
                    OR
                    (
                        CASE
                            WHEN jsonb_typeof(state_value->'failures') = 'number'
                                 AND (state_value->>'failures') ~ '^[0-9]+$'
                            THEN (state_value->>'failures')::int
                            ELSE 0
                        END
                    ) >= $3
              )
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
        max_failures,
        list(_CANDIDATE_NETWORKS),
    )
    return count


async def delete_invalid_candidates(brotr: Brotr) -> int:
    """Remove persisted validator candidates that no longer satisfy the typed contract.

    Deletes CHECKPOINT rows whose payload or state key cannot be decoded into a
    [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint].
    This prevents permanently unprocessable candidate tombstones from lingering
    in ``service_state`` and blocking rediscovery of the same relay URL.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        Number of invalid candidate rows deleted.
    """
    store = ServiceStateStore(brotr)
    states = await store.get(ServiceName.VALIDATOR, ServiceStateType.CHECKPOINT)
    invalid_states = []
    for state in states:
        try:
            ServiceStateStore.decode_candidate(state.state_key, state.state_value)
        except (KeyError, TypeError, ValueError):
            invalid_states.append(state)

    if not invalid_states:
        return 0
    return await store.delete_states(invalid_states)


_CANDIDATES_WHERE = """
    FROM candidates
    WHERE failures_count IS NOT NULL
      AND attempted_at IS NOT NULL
      AND (
            failures_count = 0
         OR attempted_at < $4
      )
"""

_CANDIDATES_ORDER = """
    ORDER BY failures_count ASC,
             attempted_at ASC,
             state_key ASC
"""

_CANDIDATES_CTE = """
    WITH candidates AS (
        SELECT state_key,
               state_value,
               CASE
                   WHEN jsonb_typeof(state_value->'failures') = 'number'
                        AND (state_value->>'failures') ~ '^[0-9]+$'
                   THEN (state_value->>'failures')::int
               END AS failures_count,
               CASE
                   WHEN jsonb_typeof(state_value->'timestamp') = 'number'
                        AND (state_value->>'timestamp') ~ '^[0-9]+$'
                   THEN (state_value->>'timestamp')::bigint
               END AS attempted_at
        FROM service_state
        WHERE owner = $1
          AND state_type = $2
          AND state_value->>'network' = ANY($3)
    )
"""


async def count_candidates(
    brotr: Brotr,
    networks: list[NetworkType],
    attempted_before: int,
) -> int:
    """Count pending validation candidates for the given networks.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network types to include.
        attempted_before: Only count candidates whose last validation
            attempt ``timestamp`` is before this Unix timestamp. Candidates
            with zero failures (never attempted) are always counted.

    Returns:
        Total count of matching candidates.
    """
    count: int = await brotr.fetchval(
        f"{_CANDIDATES_CTE} SELECT count(*)::int {_CANDIDATES_WHERE}",
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
        networks,
        attempted_before,
    )
    return count


async def fetch_candidates(
    brotr: Brotr,
    networks: list[NetworkType],
    attempted_before: int,
    limit: int,
) -> list[CandidateCheckpoint]:
    """Fetch candidates prioritized by fewest failures, then oldest attempt.

    Returns candidates that either have zero failures (never attempted)
    or whose last attempt ``timestamp`` is before ``attempted_before``.
    The query may read multiple raw pages to compensate for malformed
    persisted rows that are rejected during typed decode, so a leading
    corrupted candidate cannot make a non-empty workset appear empty.

    Rows whose ``state_key`` is not a valid relay URL are skipped
    with a warning.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        networks: Network types to include.
        attempted_before: Only fetch candidates whose last validation
            attempt ``timestamp`` is before this Unix timestamp. Candidates
            with zero failures (never attempted) are always included.
        limit: Maximum candidates to return.

    Returns:
        List of [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint]
        instances.
    """
    candidates: list[CandidateCheckpoint] = []
    offset = 0

    while len(candidates) < limit:
        raw_limit = limit - len(candidates)
        rows = await brotr.fetch(
            f"""
            {_CANDIDATES_CTE}
            SELECT state_key, state_value
            {_CANDIDATES_WHERE}
            {_CANDIDATES_ORDER}
            LIMIT $5
            OFFSET $6
            """,
            ServiceName.VALIDATOR,
            ServiceStateType.CHECKPOINT,
            networks,
            attempted_before,
            raw_limit,
            offset,
        )
        if not rows:
            break
        offset += len(rows)

        for row in rows:
            try:
                candidates.append(
                    ServiceStateStore.decode_candidate(row["state_key"], row["state_value"])
                )
            except (ValueError, TypeError) as e:
                logger.warning("invalid_candidate_skipped: %s (%s)", row["state_key"], e)

        if len(rows) < raw_limit:
            break
    return candidates


async def promote_candidates(brotr: Brotr, candidates: list[CandidateCheckpoint]) -> int:
    """Insert relays and remove their candidate records.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        candidates: Validated
            [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint] objects
            to promote from ``service_state`` to the relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ``ON CONFLICT``).
    """
    if not candidates:
        return 0

    relays = [Relay(c.key) for c in candidates]
    inserted = await batched_insert(brotr, relays, brotr.insert_relay)

    await ServiceStateStore(brotr).delete_keys(
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
        [candidate.key for candidate in candidates],
    )
    return inserted


async def fail_candidates(brotr: Brotr, candidates: list[CandidateCheckpoint]) -> int:
    """Increment the failure counter on invalid candidates.

    Builds [ServiceState][bigbrotr.models.service_state.ServiceState] records
    with ``failures + 1`` and upserts them.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        candidates: [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint]
            objects that failed validation.

    Returns:
        Number of records upserted.
    """
    if not candidates:
        return 0

    now = int(time.time())
    records = [
        ServiceStateStore.encode_candidate(
            candidate,
            timestamp=now,
            failures=candidate.failures + 1,
        )
        for candidate in candidates
    ]
    return await ServiceStateStore(brotr).upsert(records)
