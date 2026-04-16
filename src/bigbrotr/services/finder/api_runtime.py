"""Runtime helpers for Finder API-source discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bigbrotr.services.common.types import ApiCheckpoint


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping

    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay
    from bigbrotr.services.finder.configs import ApiSourceConfig


@dataclass(frozen=True, slots=True)
class ApiSourceAttempt:
    """One API source that is eligible to be fetched in the current cycle."""

    source: ApiSourceConfig
    last_checked: int


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
