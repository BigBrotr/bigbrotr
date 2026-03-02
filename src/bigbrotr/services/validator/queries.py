"""Validator-specific database queries."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.relay import Relay
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.types import CandidateCheckpoint


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr

    from .service import Validator


logger = logging.getLogger(__name__)


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
        ServiceStateType.CHECKPOINT,
    )
    new_urls = {row["url"] for row in rows}
    return [r for r in relays if r.url in new_urls]


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
    """
    new_relays = await _filter_new_relays(brotr, relays)
    if not new_relays:
        return 0

    now = int(time.time())
    records: list[ServiceState] = [
        ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=relay.url,
            state_value={
                "network": relay.network.value,
                "failures": 0,
                "timestamp": now,
            },
        )
        for relay in new_relays
    ]
    total = 0
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        total += await brotr.upsert_service_state(records[i : i + batch_size])
    return total


async def delete_promoted_candidates(validator: Validator) -> int:
    """Remove candidates that have already been promoted to the relay table.

    Deletes CHECKPOINT records whose ``state_key`` matches a URL that now
    exists in the ``relay`` table.  Called during cleanup as a safety net
    for candidates that were validated but whose deletion after promotion
    failed.

    Args:
        validator: The [Validator][bigbrotr.services.validator.Validator]
            instance.

    Returns:
        Number of deleted rows.
    """
    count: int = await validator._brotr.fetchval(
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
    ) or 0
    return count


async def delete_exhausted_candidates(validator: Validator) -> int:
    """Remove candidates that have exceeded the failure threshold.

    Deletes CHECKPOINT records whose ``failures`` counter meets or exceeds
    ``validator._config.cleanup.max_failures``. Called during cleanup when
    ``cleanup.enabled`` is ``True`` to prevent permanently broken relays from
    consuming validation resources indefinitely.

    Args:
        validator: The [Validator][bigbrotr.services.validator.Validator]
            instance; provides both the database handle and the configured
            ``max_failures`` threshold.

    Returns:
        Number of deleted rows.
    """
    count: int = await validator._brotr.fetchval(
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
        validator._config.cleanup.max_failures,
    )
    return count


async def count_candidates(
    validator: Validator,
    networks: list[NetworkType],
    attempted_before: int,
) -> int:
    """Count pending validation candidates for the given networks.

    Args:
        validator: The [Validator][bigbrotr.services.validator.Validator] instance.
        networks: Network types to include.
        attempted_before: Only count candidates whose last validation
            attempt ``timestamp`` is before this Unix timestamp. Candidates
            with zero failures (never attempted) are always counted.

    Returns:
        Total count of matching candidates.
    """
    row = await validator._brotr.fetchrow(
        """
        SELECT COUNT(*)::int AS count
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
    return row["count"] if row else 0


async def fetch_candidates(
    validator: Validator,
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
        validator: The [Validator][bigbrotr.services.validator.Validator] instance.
        networks: Network types to include.
        attempted_before: Only fetch candidates whose last validation
            attempt ``timestamp`` is before this Unix timestamp. Candidates
            with zero failures (never attempted) are always included.
        limit: Maximum candidates to return.

    Returns:
        List of [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint]
        instances.
    """
    rows = await validator._brotr.fetch(
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
            logger.warning("Skipping invalid candidate URL %s: %s", row["state_key"], e)
    return candidates


async def promote_candidates(validator: Validator, candidates: list[CandidateCheckpoint]) -> int:
    """Insert relays and remove their candidate records.

    Args:
        validator: The [Validator][bigbrotr.services.validator.Validator] instance.
        candidates: Validated
            [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint] objects
            to promote from ``service_state`` to the relays table.

    Returns:
        Number of relays inserted (duplicates skipped via ``ON CONFLICT``).
    """
    if not candidates:
        return 0

    relays = [Relay(c.key) for c in candidates]
    inserted = 0
    batch_size = validator._brotr.config.batch.max_size
    for i in range(0, len(relays), batch_size):
        inserted += await validator._brotr.insert_relay(relays[i : i + batch_size])

    for i in range(0, len(candidates), batch_size):
        chunk = candidates[i : i + batch_size]
        await validator._brotr.delete_service_state(
            [ServiceName.VALIDATOR] * len(chunk),
            [ServiceStateType.CHECKPOINT] * len(chunk),
            [c.key for c in chunk],
        )
    return inserted


async def fail_candidates(validator: Validator, candidates: list[CandidateCheckpoint]) -> int:
    """Increment the failure counter on invalid candidates.

    Builds [ServiceState][bigbrotr.models.service_state.ServiceState] records
    with ``failures + 1`` and upserts them.

    Args:
        validator: The [Validator][bigbrotr.services.validator.Validator] instance.
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
    total = 0
    batch_size = validator._brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        total += await validator._brotr.upsert_service_state(records[i : i + batch_size])
    return total
