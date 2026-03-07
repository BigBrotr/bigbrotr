"""Monitor-specific database queries."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.queries import batched_insert, upsert_service_states
from bigbrotr.services.common.utils import parse_relay_row


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.models.constants import NetworkType
    from bigbrotr.models.relay_metadata import RelayMetadata


logger = logging.getLogger(__name__)


async def delete_stale_checkpoints(brotr: Brotr, keep_keys: list[str]) -> int:
    """Remove stale monitor checkpoints.

    Deletes every monitor CHECKPOINT whose ``state_key`` neither exists
    as a relay URL in the ``relay`` table nor appears in ``keep_keys``.
    This covers both orphaned relay markers (relay deleted) and orphaned
    named keys (feature disabled) in one pass.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        keep_keys: Named keys to preserve (e.g. ``["announcement", "profile"]``
            for enabled publishing features).

    Returns:
        Number of deleted rows.
    """
    count: int = await brotr.fetchval(
        """
        WITH deleted AS (
            DELETE FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND state_key != ALL($3)
              AND NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
        keep_keys,
    )
    return count


_RELAYS_TO_MONITOR_WHERE = """
    FROM relay r
    LEFT JOIN service_state ss ON
        ss.service_name = $3
        AND ss.state_type = $4
        AND ss.state_key = r.url
    WHERE
        r.network = ANY($1)
        AND (ss.state_key IS NULL
             OR (ss.state_value->>'timestamp')::BIGINT < $2)
"""


async def count_relays_to_monitor(
    brotr: Brotr,
    monitored_before: int,
    networks: list[NetworkType],
) -> int:
    """Count relays due for monitoring.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        monitored_before: Exclusive upper bound -- only relays whose
            checkpoint ``timestamp`` is before this Unix timestamp (or NULL)
            are counted.
        networks: Network types to include.

    Returns:
        Total count of matching relays.
    """
    count: int = await brotr.fetchval(
        f"SELECT count(*)::int {_RELAYS_TO_MONITOR_WHERE}",
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
    )
    return count


async def fetch_relays_to_monitor(
    brotr: Brotr,
    monitored_before: int,
    networks: list[NetworkType],
    limit: int,
) -> list[Relay]:
    """Fetch relays due for monitoring, ordered by least-recently-monitored.

    Returns relays that have never been monitored or whose last monitoring
    occurred before ``monitored_before``.  Ordering ensures that relays
    with the oldest (or missing) monitoring marker are monitored first.
    Rows that fail ``Relay`` construction are skipped.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        monitored_before: Exclusive upper bound -- only relays whose
            checkpoint ``timestamp`` is before this Unix timestamp (or NULL)
            are returned.
        networks: Network types to include.
        limit: Maximum relays to return.

    Returns:
        List of [Relay][bigbrotr.models.relay.Relay] instances.
    """
    rows = await brotr.fetch(
        f"""
        SELECT r.url, r.network, r.discovered_at
        {_RELAYS_TO_MONITOR_WHERE}
        ORDER BY
            COALESCE((ss.state_value->>'timestamp')::BIGINT, 0) ASC,
            r.discovered_at ASC
        LIMIT $5
        """,
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
        limit,
    )
    relays: list[Relay] = []
    for row in rows:
        relay = parse_relay_row(row)
        if relay is not None:
            relays.append(relay)
    return relays


async def insert_relay_metadata(brotr: Brotr, records: list[RelayMetadata]) -> int:
    """Batch-insert relay-metadata junction records.

    Splits *records* into batches respecting
    [BatchConfig.max_size][bigbrotr.core.brotr.BatchConfig] and delegates
    each chunk to
    [Brotr.insert_relay_metadata()][bigbrotr.core.brotr.Brotr.insert_relay_metadata]
    (cascade mode).

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        records: [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
            instances to insert.

    Returns:
        Number of new relay-metadata records inserted.
    """
    return await batched_insert(brotr, records, brotr.insert_relay_metadata)


async def save_monitoring_markers(brotr: Brotr, relays: list[Relay], now: int) -> None:
    """Upsert monitoring checkpoint markers for a batch of relays.

    Called after each health-check chunk to record the timestamp of the
    last check, preventing the same relay from being re-checked within the
    same discovery interval.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: Relays that were checked (successful and failed).
        now: Unix timestamp to store as the checkpoint value.
    """
    records: list[ServiceState] = [
        ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=relay.url,
            state_value={"timestamp": now},
        )
        for relay in relays
    ]
    await upsert_service_states(brotr, records)


_PUBLISH_KEYS: frozenset[str] = frozenset({"announcement", "profile"})


def _validate_publish_key(state_key: str) -> None:
    if state_key not in _PUBLISH_KEYS:
        msg = f"invalid publish key {state_key!r}, expected one of {sorted(_PUBLISH_KEYS)}"
        raise ValueError(msg)


async def is_publish_due(brotr: Brotr, state_key: str, interval: float) -> bool:
    """Check whether enough time has elapsed since the last publish checkpoint.

    Args:
        brotr: Database interface.
        state_key: Checkpoint key — must be one of ``"announcement"``
            or ``"profile"``.
        interval: Minimum seconds between publishes.

    Returns:
        ``True`` if the interval has elapsed or no checkpoint exists.

    Raises:
        ValueError: If *state_key* is not in the whitelist.
    """
    _validate_publish_key(state_key)
    results = await brotr.get_service_state(
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
        state_key,
    )
    if not results:
        return True
    last_ts: int = results[0].state_value.get("timestamp", 0)
    return time.time() - last_ts >= interval


async def save_publish_checkpoint(brotr: Brotr, state_key: str) -> None:
    """Save the current time as a publish checkpoint.

    Args:
        brotr: Database interface.
        state_key: Checkpoint key — must be one of ``"announcement"``
            or ``"profile"``.

    Raises:
        ValueError: If *state_key* is not in the whitelist.
    """
    _validate_publish_key(state_key)
    now = int(time.time())
    await brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=state_key,
                state_value={"timestamp": now},
            ),
        ]
    )
