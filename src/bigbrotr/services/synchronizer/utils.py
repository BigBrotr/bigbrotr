"""Synchronizer service utilities.

Filter building and event insertion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nostr_sdk import (
    Alphabet,
    Filter,
    Kind,
    SingleLetterTag,
)

from bigbrotr.models import Event, EventRelay

from .queries import insert_event_relays


if TYPE_CHECKING:
    from collections.abc import Iterable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay

    from .configs import FilterConfig


__all__ = [
    "build_filter",
    "build_filters",
    "insert_events",
]


# ── Filter building ────────────────────────────────────────────────


def build_filter(config: FilterConfig) -> Filter:
    """Build a base nostr-sdk ``Filter`` from a FilterConfig (no since/until/limit).

    The returned filter contains only content criteria (ids, kinds, authors,
    tags). Time range and limit are applied per-window by the sync algorithm.

    See Also:
        [FilterConfig][bigbrotr.services.synchronizer.FilterConfig]:
            The configuration model consumed by this function.
    """
    f = Filter()

    if config.ids:
        f = f.ids(config.ids)
    if config.kinds:
        f = f.kinds([Kind(k) for k in config.kinds])
    if config.authors:
        f = f.authors(config.authors)

    if config.tags:
        for tag_letter, values in config.tags.items():
            alphabet = getattr(Alphabet, tag_letter.upper())
            if tag_letter.isupper():
                tag = SingleLetterTag.uppercase(alphabet)
            else:
                tag = SingleLetterTag.lowercase(alphabet)
            for value in values:
                f = f.custom_tag(tag, value)

    return f


def build_filters(configs: list[FilterConfig]) -> list[Filter]:
    """Build a list of base nostr-sdk ``Filter`` objects from multiple FilterConfigs.

    Each FilterConfig produces one Filter; combined they form an OR query
    per NIP-01 REQ semantics.
    """
    return [build_filter(c) for c in configs]


# ── Event insertion ────────────────────────────────────────────────


async def insert_events(
    events: Iterable[Event],
    relay: Relay,
    brotr: Brotr,
) -> int:
    """Insert pre-validated domain events into the database.

    Events are already ``Event`` domain models — this function wraps them
    in ``EventRelay`` for relay attribution and batch-inserts.

    Args:
        events: Domain ``Event`` objects (from ``iter_relay_events``).
        relay: Source [Relay][bigbrotr.models.relay.Relay] for attribution.
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    Returns:
        Number of events inserted.
    """
    event_relays = [EventRelay(evt, relay) for evt in events]

    if not event_relays:
        return 0

    return await insert_event_relays(brotr, event_relays)
