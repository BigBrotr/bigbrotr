"""Helpers for long-lived DVM request subscriptions."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nostr_sdk import Filter, Kind, RelayUrl, Timestamp

from bigbrotr.utils.protocol import normalize_send_output


if TYPE_CHECKING:
    from nostr_sdk import Client

    from bigbrotr.core.logger import Logger


@dataclass(frozen=True, slots=True)
class RequestSubscriptionState:
    """State created when a DVM request subscription starts."""

    queue: asyncio.Queue[Any]
    subscription_id: str
    task: asyncio.Task[None]


class RequestNotificationBuffer:
    """Buffer long-lived DVM subscription notifications into an asyncio queue."""

    __slots__ = ("_logger", "_loop", "_queue", "_subscription_id")

    def __init__(
        self,
        *,
        subscription_id: str,
        queue: asyncio.Queue[Any],
        logger: Logger,
    ) -> None:
        self._subscription_id = subscription_id
        self._queue = queue
        self._loop = asyncio.get_running_loop()
        self._logger = logger

    def handle_msg(self, relay_url: RelayUrl, msg: Any) -> None:
        relay_msg = msg.as_enum()
        relay = str(relay_url)

        if (
            relay_msg.is_END_OF_STORED_EVENTS()
            and relay_msg.subscription_id == self._subscription_id
        ):
            self._logger.debug(
                "request_subscription_eose",
                relay=relay,
                subscription_id=relay_msg.subscription_id,
            )
        elif relay_msg.is_CLOSED() and relay_msg.subscription_id == self._subscription_id:
            self._logger.warning(
                "request_subscription_closed",
                relay=relay,
                subscription_id=relay_msg.subscription_id,
                message=relay_msg.message,
            )
        elif relay_msg.is_NOTICE():
            self._logger.debug(
                "request_subscription_notice",
                relay=relay,
                message=relay_msg.message,
            )

    def handle(self, _relay_url: RelayUrl, subscription_id: str, event: Any) -> None:
        if subscription_id != self._subscription_id or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)


async def start_request_subscription(
    *,
    client: Client,
    connected_relays: tuple[str, ...],
    kind: int,
    since: int,
    logger: Logger,
) -> RequestSubscriptionState:
    """Subscribe a client to long-lived DVM job request notifications."""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    filter_ = Filter().kind(Kind(kind)).since(Timestamp.from_secs(since))
    urls = [RelayUrl.parse(url) for url in connected_relays]
    output = await client.subscribe_to(urls, filter_)
    successful_relays, failed_relays = normalize_send_output(output)

    for relay_url, error in failed_relays.items():
        logger.warning(
            "request_subscription_relay_failed",
            url=relay_url,
            error=error,
        )
    if not successful_relays:
        raise TimeoutError("dvm could not subscribe to any relay")

    handler = RequestNotificationBuffer(
        subscription_id=output.id,
        queue=queue,
        logger=logger,
    )
    task = asyncio.create_task(client.handle_notifications(handler))
    logger.info(
        "request_subscription_started",
        subscription_id=output.id,
        relays=len(successful_relays),
        since=since,
    )
    return RequestSubscriptionState(
        queue=queue,
        subscription_id=output.id,
        task=task,
    )


async def stop_request_subscription(
    task: asyncio.Task[None] | None,
    *,
    logger: Logger,
) -> None:
    """Stop a DVM request subscription notification loop."""
    if task is None:
        return
    if task.done():
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning(
                "request_subscription_task_failed_on_shutdown",
                error=str(error),
                error_type=type(error).__name__,
            )
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
