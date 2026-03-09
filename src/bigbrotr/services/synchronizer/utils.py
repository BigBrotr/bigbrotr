"""Synchronizer service utilities.

Event insertion helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.models import Event, EventRelay

from .queries import insert_event_relays


if TYPE_CHECKING:
    from collections.abc import Iterable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


__all__ = [
    "insert_events",
]


async def insert_events(
    events: Iterable[Event],
    relay: Relay,
    brotr: Brotr,
) -> int:
    """Insert pre-validated domain events into the database.

    Events are already ``Event`` domain models — this function wraps them
    in ``EventRelay`` for relay attribution and batch-inserts.

    Args:
        events: Domain ``Event`` objects (from ``stream_events``).
        relay: Source [Relay][bigbrotr.models.relay.Relay] for attribution.
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        Number of events inserted.
    """
    event_relays = [EventRelay(evt, relay) for evt in events]

    if not event_relays:
        return 0

    return await insert_event_relays(brotr, event_relays)
