"""Runtime helpers for synchronization cycles."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .queries import count_cursors_to_sync, insert_event_relays, upsert_sync_cursors


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence
    from typing import TypeAlias

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import EventRelay
    from bigbrotr.models.constants import NetworkType
    from bigbrotr.services.common.types import SyncCursor

    from .configs import SynchronizerConfig

    CursorCounter: TypeAlias = Callable[[Brotr, int, Sequence[NetworkType]], Awaitable[int]]
    EventRelayInserter: TypeAlias = Callable[[Brotr, list[EventRelay]], Awaitable[int]]
    SyncCursorUpserter: TypeAlias = Callable[[Brotr, Iterable[SyncCursor]], Awaitable[None]]


class NetworkSemaphoreBudget(Protocol):
    def max_concurrency(self, networks: list[NetworkType]) -> int: ...


@dataclass(frozen=True, slots=True)
class SyncCyclePlan:
    """Computed inputs for one synchronization cycle."""

    networks: tuple[NetworkType, ...]
    end_time: int
    total_relays: int
    batch_size: int
    max_concurrency: int
    page_size: int
    deadline: float


async def build_sync_cycle_plan(
    *,
    brotr: Brotr,
    config: SynchronizerConfig,
    network_semaphores: NetworkSemaphoreBudget,
    count_cursors: CursorCounter | None = None,
) -> SyncCyclePlan | None:
    """Compute the enabled networks and batching budget for one cycle."""
    networks = tuple(config.networks.get_enabled_networks())
    if not networks:
        return None

    end_time = config.processing.get_end_time()
    count_cursors_fn = count_cursors or count_cursors_to_sync
    total_relays = await count_cursors_fn(brotr, end_time, list(networks))
    batch_size = config.processing.batch_size
    max_concurrency = network_semaphores.max_concurrency(list(networks))
    return SyncCyclePlan(
        networks=networks,
        end_time=end_time,
        total_relays=total_relays,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
        page_size=max(batch_size, max_concurrency),
        deadline=time.monotonic() + config.timeouts.max_duration,
    )


async def flush_sync_batch(
    brotr: Brotr,
    buffer: list[EventRelay],
    pending_cursors: dict[str, SyncCursor],
    *,
    insert_event_relays_fn: EventRelayInserter | None = None,
    upsert_sync_cursors_fn: SyncCursorUpserter | None = None,
) -> int:
    """Persist one accumulated sync batch and clear in-memory state."""
    events_synced = 0
    insert_event_relays_impl = insert_event_relays_fn or insert_event_relays
    upsert_sync_cursors_impl = upsert_sync_cursors_fn or upsert_sync_cursors
    if buffer:
        records_batch = list(buffer)
        events_synced = await insert_event_relays_impl(brotr, records_batch)
        buffer.clear()
    if pending_cursors:
        cursors_batch = tuple(pending_cursors.values())
        await upsert_sync_cursors_impl(brotr, cursors_batch)
        pending_cursors.clear()
    return events_synced
