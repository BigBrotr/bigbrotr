"""Client lifecycle helpers behind the public protocol facade.

These helpers provide best-effort teardown for short-lived ``nostr_sdk``
clients created by the shared protocol layer. Cleanup intentionally tries to
unsubscribe, remove relays, wipe any client-local database state exposed by
the SDK, and then shut the client down, while suppressing teardown errors so
callers can keep their own failure handling focused on the primary operation.
"""

from __future__ import annotations

import contextlib
import inspect
from typing import TYPE_CHECKING, TypeVar, cast


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client


T = TypeVar("T")


async def _await_if_needed(value: T | Awaitable[T]) -> T:
    """Await ``value`` when it is awaitable, otherwise return it as-is."""
    if inspect.isawaitable(value):
        return await cast("Awaitable[T]", value)
    return value


def _database_wipe_call(database: object) -> Callable[[], object] | None:
    """Return the optional wipe callable exposed by a client-local database handle."""
    wipe = getattr(database, "wipe", None)
    if callable(wipe):
        return cast("Callable[[], object]", wipe)
    return None


async def shutdown_client(client: Client) -> None:
    """Best-effort release of a ``nostr_sdk.Client`` and its local state."""
    with contextlib.suppress(Exception):
        await _await_if_needed(client.unsubscribe_all())
    with contextlib.suppress(Exception):
        await _await_if_needed(client.force_remove_all_relays())
    with contextlib.suppress(Exception):
        database = await _await_if_needed(client.database())
        wipe = _database_wipe_call(database)
        if wipe is not None:
            await _await_if_needed(wipe())
    with contextlib.suppress(Exception):
        await _await_if_needed(client.shutdown())
