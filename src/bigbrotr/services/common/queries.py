"""Shared database query utilities for BigBrotr services.

Provides batch-insert helpers and cross-service state operations that
are used by more than one service's ``queries`` module.

See Also:
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade that provides
        ``fetch()``, ``fetchrow()``, ``fetchval()``, ``execute()``,
        and ``transaction()`` methods used by every query function.
    [ServiceState][bigbrotr.models.service_state.ServiceState]: Dataclass
        used for candidate and cursor records in ``service_state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.service_state import ServiceState

_T = TypeVar("_T")


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
