"""Runtime helpers for Finder API-source discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from bigbrotr.services.common.types import ApiCheckpoint


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
    from typing import TypeAlias

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay
    from bigbrotr.services.finder.configs import ApiSourceConfig

    InsertRelaysAsCandidates: TypeAlias = Callable[[Brotr, list[Relay]], Awaitable[int]]


class GaugeSetter(Protocol):
    """Subset of metric gauge updates used by finder API runtime helpers."""

    def __call__(self, name: str, value: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ApiSourceAttempt:
    """One API source that is eligible to be fetched in the current cycle."""

    source: ApiSourceConfig
    last_checked: int


@dataclass(frozen=True, slots=True)
class ApiDiscoveryWorkerContext:
    """Dependencies for one finder API-discovery cycle."""

    brotr: Brotr
    cooldown: int
    now: int
    max_response_size: int
    request_delay: float
    is_running: Callable[[], bool]
    wait: Callable[[float], Awaitable[bool]]
    fetch_api_fn: Callable[[Any, ApiSourceConfig, int], Awaitable[list[Relay]]]
    client_session_factory: Callable[[], Any]
    recoverable_errors: tuple[type[BaseException], ...]
    checkpoint_timestamp: Callable[[], int]
    logger: Logger
    fetch_api_checkpoints_fn: Callable[[Brotr, list[str]], Awaitable[Sequence[ApiCheckpoint]]]


@dataclass(frozen=True, slots=True)
class ApiDiscoveryPersistenceContext:
    """Dependencies for persisting finder API-discovery results."""

    brotr: Brotr
    upsert_api_checkpoints_fn: Callable[[Brotr, list[ApiCheckpoint]], Awaitable[None]]
    insert_relays_fn: InsertRelaysAsCandidates
    set_gauge: GaugeSetter


def build_api_source_attempts(
    sources: list[ApiSourceConfig],
    checkpoint_map: Mapping[str, ApiCheckpoint],
    *,
    cooldown: int,
    now: int,
    logger: Logger,
) -> tuple[ApiSourceAttempt, ...]:
    """Return the enabled API sources whose cooldown has elapsed for this cycle."""
    attempts: list[ApiSourceAttempt] = []
    for source in sources:
        last_checked = checkpoint_map[source.url].timestamp
        if now - last_checked < cooldown:
            logger.debug(
                "api_skipped",
                url=source.url,
                seconds_left=cooldown - (now - last_checked),
            )
            continue
        attempts.append(ApiSourceAttempt(source=source, last_checked=last_checked))
    return tuple(attempts)


async def stream_api_discovery_attempts(  # noqa: PLR0913
    sources: list[ApiSourceConfig],
    checkpoint_map: Mapping[str, ApiCheckpoint],
    *,
    cooldown: int,
    now: int,
    max_response_size: int,
    request_delay: float,
    is_running: Callable[[], bool],
    wait: Callable[[float], Awaitable[bool]],
    fetch_api_fn: Callable[[Any, ApiSourceConfig, int], Awaitable[list[Relay]]],
    client_session_factory: Callable[[], Any],
    recoverable_errors: tuple[type[BaseException], ...],
    checkpoint_timestamp: Callable[[], int],
    logger: Logger,
) -> AsyncGenerator[tuple[list[Relay], ApiCheckpoint], None]:
    """Fetch all API sources whose cooldown has elapsed and yield discovered relays."""
    attempts = build_api_source_attempts(
        sources,
        checkpoint_map,
        cooldown=cooldown,
        now=now,
        logger=logger,
    )

    async with client_session_factory() as session:
        for i, attempt in enumerate(attempts):
            source = attempt.source
            if not is_running():
                return

            try:
                relays = await fetch_api_fn(session, source, max_response_size)
                logger.debug("api_fetched", url=source.url, count=len(relays))
                yield relays, ApiCheckpoint(key=source.url, timestamp=checkpoint_timestamp())
            except recoverable_errors as e:
                logger.warning(
                    "api_fetch_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    url=source.url,
                )

            if request_delay > 0 and i < len(attempts) - 1 and await wait(request_delay):
                return


async def find_from_api_worker(
    *,
    sources: list[ApiSourceConfig],
    context: ApiDiscoveryWorkerContext,
) -> AsyncGenerator[tuple[list[Relay], ApiCheckpoint], None]:
    """Load checkpoints and stream all eligible API discovery attempts."""
    source_urls = [source.url for source in sources]
    checkpoints = await context.fetch_api_checkpoints_fn(context.brotr, source_urls)
    checkpoint_map = {checkpoint.key: checkpoint for checkpoint in checkpoints}
    async for relays, checkpoint in stream_api_discovery_attempts(
        sources,
        checkpoint_map,
        cooldown=context.cooldown,
        now=context.now,
        max_response_size=context.max_response_size,
        request_delay=context.request_delay,
        is_running=context.is_running,
        wait=context.wait,
        fetch_api_fn=context.fetch_api_fn,
        client_session_factory=context.client_session_factory,
        recoverable_errors=context.recoverable_errors,
        checkpoint_timestamp=context.checkpoint_timestamp,
        logger=context.logger,
    ):
        yield relays, checkpoint


async def persist_api_discovery_results(
    *,
    buffer: list[Relay],
    pending_checkpoints: list[ApiCheckpoint],
    context: ApiDiscoveryPersistenceContext,
) -> int:
    """Persist one API discovery cycle and clear its in-memory state."""
    if pending_checkpoints:
        checkpoints_batch = list(pending_checkpoints)
        await context.upsert_api_checkpoints_fn(context.brotr, checkpoints_batch)
        pending_checkpoints.clear()

    relays_batch = list(buffer)
    found = await context.insert_relays_fn(context.brotr, relays_batch)
    context.set_gauge("candidates_found_from_api", found)
    buffer.clear()
    return found
