"""Chunk processing helpers for the monitor service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .queries import insert_relay_metadata, upsert_monitor_checkpoints
from .utils import CheckResult, MonitorChunkOutcome, MonitorProgress, collect_metadata


if TYPE_CHECKING:
    from asyncio import Semaphore
    from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay, RelayMetadata
    from bigbrotr.models.constants import NetworkType

    from .configs import MetadataFlags

    MonitorCheckRelay = Callable[[Relay], Awaitable[CheckResult]]
    MonitorPublishDiscovery = Callable[[Relay, CheckResult], Awaitable[None]]
    MonitorGaugeIncrement = Callable[[str], None]
    MonitorGaugeSetter = Callable[[str, int], None]
    MonitorRelayWorker = Callable[[Relay], AsyncGenerator[tuple[Relay, CheckResult | None], None]]
    MonitorInsertRelayMetadata = Callable[[Brotr, list[RelayMetadata]], Awaitable[int]]
    MonitorUpsertCheckpoints = Callable[[Brotr, list[Relay], int], Awaitable[None]]


class MonitorSemaphoreLookup(Protocol):
    """Subset of the network semaphore API needed by monitor workers."""

    def get(self, network: NetworkType) -> Semaphore | None: ...


class MonitorConcurrentIterator(Protocol):
    """Subset of concurrent iteration used by monitor chunk processing."""

    def __call__(
        self,
        items: list[Relay],
        worker: MonitorRelayWorker,
        *,
        max_concurrency: int,
    ) -> AsyncIterator[tuple[Relay, CheckResult | None]]: ...


@dataclass(frozen=True, slots=True)
class MonitorWorkerContext:
    """Dependencies for per-relay worker execution."""

    network_semaphores: MonitorSemaphoreLookup
    logger: Logger
    check_relay: MonitorCheckRelay
    publish_discovery: MonitorPublishDiscovery


@dataclass(frozen=True, slots=True)
class MonitorChunkContext:
    """Dependencies for one monitor chunk execution."""

    iter_concurrent: MonitorConcurrentIterator
    worker: MonitorRelayWorker
    inc_gauge: MonitorGaugeIncrement


@dataclass(frozen=True, slots=True)
class MonitorChunkPersistence:
    """Dependencies for persisting processed monitor chunks."""

    brotr: Brotr
    store: MetadataFlags
    insert_relay_metadata: MonitorInsertRelayMetadata = insert_relay_metadata
    upsert_monitor_checkpoints: MonitorUpsertCheckpoints = upsert_monitor_checkpoints


async def monitor_worker(
    *,
    context: MonitorWorkerContext,
    relay: Relay,
) -> AsyncGenerator[tuple[Relay, CheckResult | None], None]:
    """Check and optionally publish one relay for use with concurrent chunk iteration."""
    try:
        semaphore = context.network_semaphores.get(relay.network)
        if semaphore is None:
            context.logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            yield relay, None
            return

        async with semaphore:
            result = await context.check_relay(relay)
            if not result.has_data:
                yield relay, None
                return
            await context.publish_discovery(relay, result)
            yield relay, result
    except Exception as error:  # Worker exception boundary — protects TaskGroup
        context.logger.error(
            "check_relay_failed",
            error=str(error),
            error_type=type(error).__name__,
            relay=relay.url,
        )
        yield relay, None


async def monitor_chunk(
    *,
    context: MonitorChunkContext,
    relays: list[Relay],
    max_concurrency: int,
) -> MonitorChunkOutcome:
    """Run one page of relay checks and classify the results."""
    chunk_successful: list[tuple[Relay, CheckResult]] = []
    chunk_failed: list[Relay] = []

    async for relay, result in context.iter_concurrent(
        relays,
        context.worker,
        max_concurrency=max_concurrency,
    ):
        if result is not None:
            chunk_successful.append((relay, result))
            context.inc_gauge("succeeded")
        else:
            chunk_failed.append(relay)
            context.inc_gauge("failed")

    return MonitorChunkOutcome(
        successful=tuple(chunk_successful),
        failed=tuple(chunk_failed),
    )


def start_monitor_progress(
    *,
    total: int,
    set_gauge: MonitorGaugeSetter,
) -> MonitorProgress:
    """Initialize gauges and progress totals for one monitor cycle."""
    set_gauge("total", total)
    set_gauge("succeeded", 0)
    set_gauge("failed", 0)
    return MonitorProgress(total=total)


async def persist_chunk_outcome(
    *,
    context: MonitorChunkPersistence,
    chunk_outcome: MonitorChunkOutcome,
    checked_at: int,
) -> None:
    """Persist one processed monitor chunk to metadata and service state."""
    metadata = collect_metadata(
        list(chunk_outcome.successful),
        context.store,
    )
    await context.insert_relay_metadata(context.brotr, metadata)
    await context.upsert_monitor_checkpoints(
        context.brotr,
        list(chunk_outcome.checked_relays),
        checked_at,
    )


def log_chunk_outcome(
    *,
    logger: Logger,
    chunk_outcome: MonitorChunkOutcome,
    total: int,
    succeeded: int,
    failed: int,
) -> None:
    """Emit the standard monitor chunk completion log line."""
    logger.info(
        "chunk_completed",
        succeeded=chunk_outcome.succeeded_count,
        failed=chunk_outcome.failed_count,
        remaining=total - succeeded - failed,
    )
