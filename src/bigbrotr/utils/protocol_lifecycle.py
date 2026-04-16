"""Client lifecycle helpers behind the public protocol facade."""

from __future__ import annotations

import contextlib
import inspect
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from nostr_sdk import Client


async def _await_if_needed(value: object) -> object:
    """Await ``value`` when it is awaitable, otherwise return it as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


async def shutdown_client(client: Client) -> None:
    """Fully release a nostr-sdk Client's resources before shutdown."""
    with contextlib.suppress(Exception):
        await _await_if_needed(client.unsubscribe_all())
    with contextlib.suppress(Exception):
        await _await_if_needed(client.force_remove_all_relays())
    with contextlib.suppress(Exception):
        database = await _await_if_needed(client.database())
        await _await_if_needed(database.wipe())  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        await _await_if_needed(client.shutdown())
