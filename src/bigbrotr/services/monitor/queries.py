"""Monitor-specific database queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.queries import upsert_service_states
from bigbrotr.services.common.utils import parse_relay_row


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay
    from bigbrotr.models.constants import NetworkType
    from bigbrotr.models.relay_metadata import RelayMetadata


logger = logging.getLogger(__name__)


async def delete_stale_checkpoints(brotr: Brotr) -> int:
    """Remove checkpoint state for relays that no longer exist.

    Deletes CHECKPOINT records whose relay-URL key (``state_key LIKE 'ws%'``)
    does not match any relay in the relay table.  Named keys such as
    ``last_announcement`` and ``last_profile`` are not touched.

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
              AND state_key LIKE 'ws%'
              AND NOT EXISTS (SELECT 1 FROM relay r WHERE r.url = state_key)
            RETURNING 1
        )
        SELECT count(*)::int FROM deleted
        """,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
    ) or 0
    return count


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
            checkpoint ``timestamp`` is before this Unix timestamp (or NULL)
            are returned.
        networks: Network types to include.

    Returns:
        List of [Relay][bigbrotr.models.relay.Relay] instances.
    """
    rows = await brotr.fetch(
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
                 OR (ss.state_value->>'timestamp')::BIGINT < $2)
        ORDER BY
            COALESCE((ss.state_value->>'timestamp')::BIGINT, 0) ASC,
            r.discovered_at ASC
        """,
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
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
    if not records:
        return 0
    total = 0
    batch_size = brotr.config.batch.max_size
    for i in range(0, len(records), batch_size):
        total += await brotr.insert_relay_metadata(records[i : i + batch_size])
    return total


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
