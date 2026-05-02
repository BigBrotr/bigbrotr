"""Client lifecycle helpers behind the public protocol facade.

These helpers provide best-effort teardown for short-lived ``nostr_sdk``
clients created by the shared protocol layer. Cleanup intentionally tries to
unsubscribe, remove relays, wipe any client-local database state exposed by
the SDK, and then shut the client down. Expected transport/SDK teardown
failures are tolerated so callers can stay focused on the primary operation,
while unexpected bugs are still surfaced after the remaining cleanup steps
have been attempted.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, TypeVar, cast

from nostr_sdk import NostrSdkError


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client


T = TypeVar("T")
_EXPECTED_TEARDOWN_ERRORS = (OSError, RuntimeError, TimeoutError, NostrSdkError)


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


async def _run_cleanup_step(
    step: Callable[[], T | Awaitable[T]],
) -> tuple[bool, T | None, Exception | None]:
    """Execute one cleanup step, classifying expected teardown failures."""
    try:
        return True, await _await_if_needed(step()), None
    except _EXPECTED_TEARDOWN_ERRORS:
        return False, None, None
    except Exception as exc:
        return False, None, exc


async def shutdown_client(client: Client) -> None:
    """Best-effort release of a ``nostr_sdk.Client`` and its local state."""
    unexpected_error: Exception | None = None

    def _record_unexpected(error: Exception | None) -> None:
        nonlocal unexpected_error
        if unexpected_error is None and error is not None:
            unexpected_error = error

    _, _, error = await _run_cleanup_step(client.unsubscribe_all)
    _record_unexpected(error)

    _, _, error = await _run_cleanup_step(client.force_remove_all_relays)
    _record_unexpected(error)

    database_ok, database, error = await _run_cleanup_step(client.database)
    _record_unexpected(error)
    if database_ok and database is not None:
        wipe = _database_wipe_call(database)
        if wipe is not None:
            _, _, error = await _run_cleanup_step(wipe)
            _record_unexpected(error)

    _, _, error = await _run_cleanup_step(client.shutdown)
    _record_unexpected(error)

    if unexpected_error is not None:
        raise unexpected_error
