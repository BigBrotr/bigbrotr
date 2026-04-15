"""Monitor-specific database queries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.paging import iter_keyset_pages
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import MonitorCheckpoint, PublishCheckpoint
from bigbrotr.services.common.utils import batched_insert, parse_relay_row


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay, RelayMetadata
    from bigbrotr.models.constants import NetworkType


@dataclass(frozen=True, slots=True)
class _MonitorRelayPageToken:
    last_monitored: int
    discovered_at: int
    relay_url: str


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
    brotr: Brotr, monitored_before: int, networks: list[NetworkType]
) -> int:
    """Count relays currently due for monitoring."""
    count: int = await brotr.fetchval(
        f"""
        SELECT count(*)::int
        {_RELAYS_TO_MONITOR_WHERE}
        """,
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
    )
    return count


async def fetch_relays_to_monitor(
    brotr: Brotr, monitored_before: int, networks: list[NetworkType]
) -> list[Relay]:
    """Fetch all relays due for monitoring, ordered by least-recently-monitored.

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
        f"""
        SELECT r.url, r.network, r.discovered_at
        {_RELAYS_TO_MONITOR_WHERE}
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


async def fetch_relays_to_monitor_page(
    brotr: Brotr,
    monitored_before: int,
    networks: list[NetworkType],
    after: _MonitorRelayPageToken | None,
    limit: int,
) -> tuple[list[Relay], _MonitorRelayPageToken | None]:
    """Fetch one page of relays due for monitoring ordered by oldest checkpoint."""
    rows = await brotr.fetch(
        f"""
        SELECT r.url,
               r.network,
               r.discovered_at,
               COALESCE((ss.state_value->>'timestamp')::BIGINT, 0) AS last_monitored
        {_RELAYS_TO_MONITOR_WHERE}
          AND (
                $5::bigint IS NULL
                OR (
                    COALESCE((ss.state_value->>'timestamp')::BIGINT, 0),
                    r.discovered_at,
                    r.url
                ) > ($5::bigint, $6::bigint, $7::text)
          )
        ORDER BY
            COALESCE((ss.state_value->>'timestamp')::BIGINT, 0) ASC,
            r.discovered_at ASC,
            r.url ASC
        LIMIT $8
        """,
        networks,
        monitored_before,
        ServiceName.MONITOR,
        ServiceStateType.CHECKPOINT,
        after.last_monitored if after is not None else None,
        after.discovered_at if after is not None else 0,
        after.relay_url if after is not None else "",
        limit,
    )
    relays: list[Relay] = []
    next_token: _MonitorRelayPageToken | None = None
    for row in rows:
        relay = parse_relay_row(row)
        if relay is None:
            continue
        relays.append(relay)
        next_token = _MonitorRelayPageToken(
            last_monitored=int(row["last_monitored"]),
            discovered_at=relay.discovered_at,
            relay_url=relay.url,
        )
    return relays, next_token


async def iter_relays_to_monitor_pages(
    brotr: Brotr,
    monitored_before: int,
    networks: list[NetworkType],
    *,
    page_size: int,
    max_relays: int | None = None,
) -> AsyncIterator[list[Relay]]:
    """Yield relay pages due for monitoring without materializing the full workset."""
    async for page in iter_keyset_pages(
        lambda after, limit: fetch_relays_to_monitor_page(
            brotr,
            monitored_before,
            networks,
            after,
            limit,
        ),
        page_size=page_size,
        max_items=max_relays,
    ):
        yield page


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
    return await batched_insert(
        brotr,
        records,
        lambda chunk: brotr.insert_relay_metadata(chunk, cascade=True),
    )


async def upsert_monitor_checkpoints(brotr: Brotr, relays: list[Relay], now: int) -> None:
    """Upsert monitoring checkpoint markers for a batch of relays.

    Called after each health-check chunk to record the timestamp of the
    last check, preventing the same relay from being re-checked within the
    same discovery interval.

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: Relays that were checked (successful and failed).
        now: Unix timestamp to store as the checkpoint value.
    """
    await ServiceStateStore(brotr).upsert_checkpoints(
        ServiceName.MONITOR,
        [MonitorCheckpoint(key=relay.url, timestamp=now) for relay in relays],
    )


# Sync with: Monitor.cleanup() keep_keys and MonitorConfig publishing sub-configs.
_PUBLISH_KEYS: frozenset[str] = frozenset({"announcement", "profile", "relay_list"})


def _validate_publish_keys(state_keys: list[str]) -> None:
    invalid = [k for k in state_keys if k not in _PUBLISH_KEYS]
    if invalid:
        msg = f"invalid publish keys {invalid!r}, expected one of {sorted(_PUBLISH_KEYS)}"
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
    _validate_publish_keys([state_key])
    results = await ServiceStateStore(brotr).fetch_checkpoints(
        ServiceName.MONITOR,
        [state_key],
        PublishCheckpoint,
    )
    last_ts = results[0].timestamp
    return time.time() - last_ts >= interval


async def upsert_publish_checkpoints(brotr: Brotr, state_keys: list[str]) -> None:
    """Save the current time as publish checkpoints.

    Args:
        brotr: Database interface.
        state_keys: Checkpoint keys — each must be one of ``"announcement"``
            or ``"profile"``.

    Raises:
        ValueError: If any key is not in the whitelist.
    """
    if not state_keys:
        return
    _validate_publish_keys(state_keys)
    now = int(time.time())
    await ServiceStateStore(brotr).upsert_checkpoints(
        ServiceName.MONITOR,
        [PublishCheckpoint(key=key, timestamp=now) for key in state_keys],
    )
