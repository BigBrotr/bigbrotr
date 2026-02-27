"""Shared domain types for BigBrotr services.

Lightweight dataclasses produced by query functions and consumed by
services.  Keeping them in their own module avoids circular imports
between ``queries`` and individual service packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Mapping

    from bigbrotr.models.relay import Relay


@dataclass(frozen=True, slots=True)
class Candidate:
    """Relay candidate pending validation.

    Wraps a [Relay][bigbrotr.models.relay.Relay] object with its
    ``service_state`` metadata, providing convenient access to validation
    state (e.g., failure count).

    Attributes:
        relay: [Relay][bigbrotr.models.relay.Relay] object with URL and
            network information.
        data: Metadata from the ``service_state`` table (``network``,
            ``failures``, etc.).

    See Also:
        [fetch_candidates][bigbrotr.services.common.queries.fetch_candidates]:
            Query that produces candidates.
    """

    relay: Relay
    data: Mapping[str, Any]

    @property
    def failures(self) -> int:
        """Return the number of failed validation attempts for this candidate."""
        return int(self.data.get("failures", 0))


@dataclass(frozen=True, slots=True)
class EventRelayCursor:
    """Per-relay cursor for event scanning pagination.

    Tracks how far event scanning has progressed for a given relay.
    The cursor position is defined by ``seen_at`` (timestamp) and
    optionally ``event_id`` (for deterministic tie-breaking within
    the same timestamp).

    Valid field combinations:

    - ``seen_at=None, event_id=None`` — no cursor, scan from beginning.
    - ``seen_at=<int>, event_id=None`` — timestamp-only cursor.
    - ``seen_at=<int>, event_id=<bytes>`` — full composite cursor.

    ``event_id`` without ``seen_at`` is invalid and rejected at
    construction.

    Attributes:
        relay_url: Relay URL this cursor belongs to.
        seen_at: Unix timestamp of the last processed event, or None.
        event_id: Raw 32-byte event ID for tie-breaking, or None.
    """

    relay_url: str
    seen_at: int | None = None
    event_id: bytes | None = None

    def __post_init__(self) -> None:
        if self.seen_at is None and self.event_id is not None:
            msg = "event_id requires seen_at"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EventCursor:
    """Cursor for paginating through Nostr events.

    Tracks the scanning position within an event stream.  The cursor
    position is defined by ``created_at`` (event timestamp) and
    optionally ``event_id`` (for deterministic tie-breaking within
    the same timestamp).

    Valid field combinations:

    - ``created_at=None, event_id=None`` — no cursor, scan from beginning.
    - ``created_at=<int>, event_id=None`` — timestamp-only cursor.
    - ``created_at=<int>, event_id=<bytes>`` — full composite cursor.

    ``event_id`` without ``created_at`` is invalid and rejected at
    construction.

    Attributes:
        created_at: Unix timestamp of the last processed event, or None.
        event_id: Raw 32-byte event ID for tie-breaking, or None.
    """

    created_at: int | None = None
    event_id: bytes | None = None

    def __post_init__(self) -> None:
        if self.created_at is None and self.event_id is not None:
            msg = "event_id requires created_at"
            raise ValueError(msg)
