"""Validator-specific database queries."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.relay import Relay
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.queries import batched_insert
from bigbrotr.services.common.types import CandidateCheckpoint


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


logger = logging.getLogger(__name__)


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
            WHERE service_name = $1
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
    resources indefinitely.

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
            WHERE service_name = $1
              AND state_type = $2
              AND COALESCE((state_value->>'failures')::int, 0) >= $3
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
        max_failures,
    )
    return count


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
        """
        SELECT COUNT(*)::int
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND state_value->>'network' = ANY($3)
          AND (COALESCE((state_value->>'failures')::int, 0) = 0
               OR (state_value->>'timestamp')::BIGINT < $4)
        """,
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
    rows = await brotr.fetch(
        """
        SELECT state_key, state_value
        FROM service_state
        WHERE service_name = $1
          AND state_type = $2
          AND state_value->>'network' = ANY($3)
          AND (COALESCE((state_value->>'failures')::int, 0) = 0
               OR (state_value->>'timestamp')::BIGINT < $4)
        ORDER BY COALESCE((state_value->>'failures')::int, 0) ASC,
                 COALESCE((state_value->>'timestamp')::BIGINT, 0) ASC
        LIMIT $5
        """,
        ServiceName.VALIDATOR,
        ServiceStateType.CHECKPOINT,
        networks,
        attempted_before,
        limit,
    )
    candidates: list[CandidateCheckpoint] = []
    for row in rows:
        try:
            sv = row["state_value"]
            candidates.append(
                CandidateCheckpoint(
                    key=row["state_key"],
                    timestamp=int(sv.get("timestamp", 0)),
                    network=NetworkType(sv.get("network", "clearnet")),
                    failures=int(sv.get("failures", 0)),
                )
            )
        except (ValueError, TypeError) as e:
            logger.warning("invalid_candidate_skipped: %s (%s)", row["state_key"], e)
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

    batch_size = brotr.config.batch.max_size
    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i : i + batch_size]
        await brotr.delete_service_state(
            [ServiceName.VALIDATOR] * len(chunk),
            [ServiceStateType.CHECKPOINT] * len(chunk),
            [c.key for c in chunk],
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
    records: list[ServiceState] = [
        ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=c.key,
            state_value={
                "network": c.network.value,
                "failures": c.failures + 1,
                "timestamp": now,
            },
        )
        for c in candidates
    ]
    return await batched_insert(brotr, records, brotr.upsert_service_state)
