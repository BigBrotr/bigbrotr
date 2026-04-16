"""Runtime helpers for synchronization cycles."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from nostr_sdk import NostrSdkError

from bigbrotr.models import EventRelay, Relay
from bigbrotr.services.common.types import SyncCursor

from .queries import count_cursors_to_sync, insert_event_relays, upsert_sync_cursors


if TYPE_CHECKING:
    from asyncio import Semaphore
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
        Sequence,
    )
    from typing import TypeAlias

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Event
    from bigbrotr.models.constants import NetworkType

    from .configs import SynchronizerConfig

    CursorCounter: TypeAlias = Callable[[Brotr, int, Sequence[NetworkType]], Awaitable[int]]
    EventRelayInserter: TypeAlias = Callable[[Brotr, list[EventRelay]], Awaitable[int]]
    SyncCursorUpserter: TypeAlias = Callable[[Brotr, Iterable[SyncCursor]], Awaitable[None]]
    StreamEvents: TypeAlias = Callable[
        [object, list[object], int, int, int, float, float, int | None],
        AsyncIterator[Event],
    ]


class NetworkSemaphoreBudget(Protocol):
    def max_concurrency(self, networks: list[NetworkType]) -> int: ...


class NetworkSemaphoreLookup(Protocol):
    """Subset of network semaphore access used by synchronizer workers."""

    def get(self, network: NetworkType) -> Semaphore | None: ...


class SyncConcurrentIterator(Protocol):
    """Subset of concurrent iteration used by synchronizer page processing."""

    def __call__(
        self,
        items: list[SyncCursor],
        worker: Callable[[SyncCursor], AsyncGenerator[tuple[Event, Relay], None]],
        *,
        max_concurrency: int,
    ) -> AsyncIterator[tuple[Event, Relay]]: ...


class GaugeIncrementer(Protocol):
    """Subset of metric gauge updates used by synchronizer runtime helpers."""

    def __call__(self, name: str, value: float = 1.0) -> None: ...


class RelayClientManager(Protocol):
    """Subset of relay client management used by synchronizer workers."""

    async def get_relay_client(self, relay: Relay) -> object | None: ...


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


@dataclass(frozen=True, slots=True)
class SyncPageContext:
    """Dependencies for synchronizing one cursor page."""

    iter_concurrent: SyncConcurrentIterator
    worker: Callable[[SyncCursor], AsyncGenerator[tuple[Event, Relay], None]]
    flush_batch: Callable[[list[EventRelay], dict[str, SyncCursor]], Awaitable[int]]
    inc_gauge: GaugeIncrementer
    logger: Logger


@dataclass(slots=True)
class SyncBatchState:
    """Mutable accumulated state for one synchronization page."""

    buffer: list[EventRelay]
    pending_cursors: dict[str, SyncCursor]


@dataclass(frozen=True, slots=True)
class SyncWorkerContext:
    """Dependencies for streaming events from one relay cursor."""

    network_semaphores: NetworkSemaphoreLookup
    logger: Logger
    is_running: Callable[[], bool]
    config: SynchronizerConfig
    client_manager: RelayClientManager
    stream_events_fn: StreamEvents
    inc_gauge: GaugeIncrementer


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


async def synchronize_cursor_page(
    *,
    cursors: list[SyncCursor],
    batch_state: SyncBatchState,
    plan: SyncCyclePlan,
    context: SyncPageContext,
    monotonic: Callable[[], float] | None = None,
) -> tuple[int, bool]:
    """Scan one page of relay cursors and flush when the batch budget is reached."""
    events_synced = 0
    monotonic_fn = monotonic or time.monotonic

    async for event, relay in context.iter_concurrent(
        cursors,
        context.worker,
        max_concurrency=plan.max_concurrency,
    ):
        batch_state.buffer.append(EventRelay(event, relay))
        batch_state.pending_cursors[relay.url] = SyncCursor(
            key=relay.url,
            timestamp=event.created_at,
            id=event.id,
        )
        context.inc_gauge("events_seen")
        if len(batch_state.buffer) == plan.batch_size:
            events_synced += await context.flush_batch(
                batch_state.buffer,
                batch_state.pending_cursors,
            )
            if monotonic_fn() > plan.deadline:
                context.logger.info("sync_timeout", events_synced=events_synced)
                return events_synced, True

    return events_synced, False


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


async def synchronize_worker(
    *,
    context: SyncWorkerContext,
    cursor: SyncCursor,
) -> AsyncGenerator[tuple[Event, Relay], None]:
    """Stream events from a single relay for use with concurrent chunk iteration."""
    relay = Relay(cursor.key)
    try:
        semaphore = context.network_semaphores.get(relay.network)
        if semaphore is None:
            context.logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return

        async with semaphore:
            if not context.is_running():
                return

            network_config = context.config.networks.get(relay.network)
            request_timeout = network_config.timeout

            client = await context.client_manager.get_relay_client(relay)
            if client is None:
                return

            try:
                async for event in context.stream_events_fn(
                    client,
                    context.config.processing.filters,
                    cursor.timestamp,
                    context.config.processing.get_end_time(),
                    context.config.processing.limit,
                    request_timeout,
                    context.config.timeouts.idle,
                    context.config.processing.max_event_size,
                ):
                    yield event, relay

            except (TimeoutError, OSError, NostrSdkError) as error:
                context.logger.warning("sync_relay_error", relay=relay.url, error=str(error))
            finally:
                context.inc_gauge("relays_seen")
    except Exception as error:  # Worker exception boundary — protects TaskGroup
        context.logger.error(
            "sync_worker_failed",
            error=str(error),
            error_type=type(error).__name__,
            relay=relay.url,
        )
