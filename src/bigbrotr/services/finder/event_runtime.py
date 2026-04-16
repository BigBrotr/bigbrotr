"""Runtime helpers for Finder event-scan orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from bigbrotr.services.common.types import FinderCursor


if TYPE_CHECKING:
    from asyncio import Semaphore
    from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay

    from .configs import FinderConfig


class _IterConcurrent(Protocol):
    """Typed protocol for the concurrent finder page iterator."""

    def __call__(
        self,
        items: list[FinderCursor],
        worker: Callable[[FinderCursor], AsyncGenerator[tuple[list[Relay], FinderCursor], None]],
        *,
        max_concurrency: int,
    ) -> AsyncIterator[tuple[list[Relay], FinderCursor]]: ...


class _IncGauge(Protocol):
    """Typed protocol for incrementing a metric gauge."""

    def __call__(self, name: str, value: float = 1.0) -> None: ...


@dataclass(frozen=True, slots=True)
class EventScanPlan:
    """Computed inputs for one event-discovery cycle."""

    relay_count: int
    batch_size: int
    max_concurrency: int
    page_size: int
    phase_start: float


@dataclass(frozen=True, slots=True)
class EventWorkerContext:
    """Shared dependencies for one finder event-scan worker."""

    event_semaphore: Semaphore
    is_running: Callable[[], bool]
    phase_start: float
    max_duration: float
    max_relay_time: float
    scan_size: int
    brotr: Brotr
    logger: Logger
    stream_event_relays: Callable[
        [Brotr, FinderCursor, int],
        AsyncGenerator[dict[str, Any], None],
    ]
    extract_relays_from_tagvalues: Callable[[list[dict[str, Any]]], list[Relay]]
    monotonic: Callable[[], float]
    inc_gauge: _IncGauge


@dataclass(frozen=True, slots=True)
class EventScanPageContext:
    """Shared dependencies for scanning one page of finder cursors."""

    iter_concurrent: _IterConcurrent
    worker: Callable[[FinderCursor], AsyncGenerator[tuple[list[Relay], FinderCursor], None]]
    flush_batch: Callable[[list[Relay], dict[str, FinderCursor]], Awaitable[int]]
    inc_gauge: _IncGauge


@dataclass(frozen=True, slots=True)
class EventScanPersistenceContext:
    """Shared dependencies for persisting finder event-scan state."""

    brotr: Brotr
    insert_relays_fn: Callable[[Brotr, list[Relay]], Awaitable[int]]
    upsert_cursors_fn: Callable[[Brotr, tuple[FinderCursor, ...]], Awaitable[None]]
    inc_gauge: _IncGauge


async def build_event_scan_plan(
    *,
    brotr: Brotr,
    config: FinderConfig,
    count_relays_fn: Callable[[Brotr], Awaitable[int]],
    monotonic: Callable[[], float] = time.monotonic,
) -> EventScanPlan | None:
    """Compute the batching budget and progress totals for one event scan cycle."""
    relay_count = await count_relays_fn(brotr)
    if relay_count == 0:
        return None

    batch_size = config.events.batch_size
    max_concurrency = config.events.parallel_relays
    return EventScanPlan(
        relay_count=relay_count,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
        page_size=max(batch_size, max_concurrency),
        phase_start=monotonic(),
    )


async def scan_event_cursor_page(
    *,
    cursors: list[FinderCursor],
    buffer: list[Relay],
    pending_cursors: dict[str, FinderCursor],
    plan: EventScanPlan,
    context: EventScanPageContext,
) -> int:
    """Scan one page of source relays and flush when the batch budget is reached."""
    total_found = 0

    async for relays, cursor in context.iter_concurrent(
        cursors,
        context.worker,
        max_concurrency=plan.max_concurrency,
    ):
        buffer.extend(relays)
        pending_cursors[cursor.key] = cursor
        context.inc_gauge("rows_seen")
        if len(buffer) >= plan.batch_size:
            total_found += await context.flush_batch(buffer, pending_cursors)

    return total_found


async def flush_event_scan_batch(
    *,
    buffer: list[Relay],
    pending_cursors: dict[str, FinderCursor],
    context: EventScanPersistenceContext,
) -> int:
    """Persist one accumulated event-scan batch and clear in-memory state."""
    found = 0
    if buffer:
        relays_batch = list(buffer)
        found = await context.insert_relays_fn(context.brotr, relays_batch)
        context.inc_gauge("candidates_found_from_events", found)
        buffer.clear()
    if pending_cursors:
        cursors_batch = tuple(pending_cursors.values())
        await context.upsert_cursors_fn(context.brotr, cursors_batch)
        pending_cursors.clear()
    return found


async def stream_event_discovery_worker(
    *,
    context: EventWorkerContext,
    cursor: FinderCursor,
) -> AsyncGenerator[tuple[list[Relay], FinderCursor], None]:
    """Stream discovered relays from one source relay for finder event scanning."""
    async with context.event_semaphore:
        if not context.is_running() or (
            context.monotonic() - context.phase_start > context.max_duration
        ):
            return
        try:
            deadline = context.monotonic() + context.max_relay_time
            async for row in context.stream_event_relays(
                context.brotr,
                cursor,
                context.scan_size,
            ):
                relays = context.extract_relays_from_tagvalues([row])
                updated = FinderCursor(
                    key=cursor.key,
                    timestamp=int(row["seen_at"]),
                    id=bytes(row["event_id"]).hex(),
                )
                yield relays, updated
                if context.monotonic() > deadline:
                    return
        except Exception as exc:  # Worker exception boundary — protects TaskGroup
            context.logger.error(
                "event_scan_worker_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                relay=cursor.key,
            )
        finally:
            context.inc_gauge("relays_seen")
