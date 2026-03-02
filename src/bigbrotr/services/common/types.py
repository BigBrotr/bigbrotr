"""Shared domain types for BigBrotr services.

Lightweight dataclasses produced by query functions and consumed by
services.  Keeping them in their own module avoids circular imports
between ``queries`` and individual service packages.

Each ``ServiceStateType`` has a corresponding typed class:

- **CHECKPOINT** → [Checkpoint][bigbrotr.services.common.types.Checkpoint]
  (with subclasses [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint],
  [MonitorCheckpoint][bigbrotr.services.common.types.MonitorCheckpoint],
  [PublishCheckpoint][bigbrotr.services.common.types.PublishCheckpoint])
- **CANDIDATE** → [Candidate][bigbrotr.services.common.types.Candidate]
- **CURSOR** → [Cursor][bigbrotr.services.common.types.Cursor]
  (with subclasses [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor],
  [EventCursor][bigbrotr.services.common.types.EventCursor])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.models.relay import Relay


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Timestamp-based progress marker stored in ``service_state``.

    Represents a CHECKPOINT record: a named key with a Unix timestamp
    tracking when the associated entity was last processed.

    Subclass per usage to enable type-level disambiguation:

    - [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
    - [MonitorCheckpoint][bigbrotr.services.common.types.MonitorCheckpoint]
    - [PublishCheckpoint][bigbrotr.services.common.types.PublishCheckpoint]

    Attributes:
        key: State key identifying the entity (relay URL, API source URL,
            or a named marker like ``"last_announcement"``).
        timestamp: Unix timestamp of the last processing event.
    """

    key: str
    timestamp: int


@dataclass(frozen=True, slots=True)
class ApiCheckpoint(Checkpoint):
    """Checkpoint for API source polling (Finder).

    Tracks when an external API endpoint was last queried for relay
    discovery.  The ``key`` is the API source URL.
    """


@dataclass(frozen=True, slots=True)
class MonitorCheckpoint(Checkpoint):
    """Checkpoint for relay health monitoring (Monitor).

    Tracks when a relay was last health-checked.  The ``key`` is the
    relay URL.
    """


@dataclass(frozen=True, slots=True)
class PublishCheckpoint(Checkpoint):
    """Checkpoint for Nostr event publishing (Monitor).

    Tracks when a periodic event (announcement, profile) was last
    published.  The ``key`` is a named marker (e.g. ``"last_announcement"``).
    """


@dataclass(frozen=True, slots=True)
class Candidate:
    """Relay candidate pending validation.

    Wraps a [Relay][bigbrotr.models.relay.Relay] with a failure counter.
    Created by
    [insert_relays_as_candidates][bigbrotr.services.common.queries.insert_relays_as_candidates]
    and fetched by
    [fetch_candidates][bigbrotr.services.common.queries.fetch_candidates].

    Attributes:
        relay: [Relay][bigbrotr.models.relay.Relay] object with URL and
            network information.
        failures: Number of failed validation attempts (0 for new candidates).
    """

    relay: Relay
    failures: int = 0


@dataclass(frozen=True, slots=True)
class Cursor:
    """Base class for pagination cursors stored in ``service_state``.

    Subclass per usage to enable type-level disambiguation:

    - [EventRelayCursor][bigbrotr.services.common.types.EventRelayCursor]
    - [EventCursor][bigbrotr.services.common.types.EventCursor]
    """


@dataclass(frozen=True, slots=True)
class EventRelayCursor(Cursor):
    """Per-relay cursor for event scanning pagination.

    Tracks how far event scanning has progressed for a given relay.
    The cursor position is defined by ``seen_at`` (timestamp) and
    ``event_id`` (for deterministic tie-breaking within the same
    timestamp).

    Valid field combinations:

    - ``seen_at=None, event_id=None`` — new cursor, scan from beginning.
    - ``seen_at=<int>, event_id=<bytes>`` — composite cursor pointing
      to a specific row.

    Partial cursors (one field set, the other ``None``) are invalid and
    rejected at construction.

    Attributes:
        relay_url: Relay URL this cursor belongs to.
        seen_at: Unix timestamp of the last processed event, or None.
        event_id: Raw 32-byte event ID for tie-breaking, or None.
    """

    relay_url: str
    seen_at: int | None = None
    event_id: bytes | None = None

    def __post_init__(self) -> None:
        if (self.seen_at is None) != (self.event_id is None):
            msg = "seen_at and event_id must both be None or both be set"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EventCursor(Cursor):
    """Cursor for paginating through Nostr events.

    Tracks the scanning position within an event stream.  The cursor
    position is defined by ``created_at`` (event timestamp) and
    optionally ``event_id`` (for deterministic tie-breaking within
    the same timestamp).

    Valid field combinations:

    - ``created_at=None, event_id=None`` — new cursor, scan from beginning.
    - ``created_at=<int>, event_id=<bytes>`` — composite cursor pointing
      to a specific row.

    Partial cursors (one field set, the other ``None``) are invalid and
    rejected at construction.

    Attributes:
        created_at: Unix timestamp of the last processed event, or None.
        event_id: Raw 32-byte event ID for tie-breaking, or None.
    """

    created_at: int | None = None
    event_id: bytes | None = None

    def __post_init__(self) -> None:
        if (self.created_at is None) != (self.event_id is None):
            msg = "created_at and event_id must both be None or both be set"
            raise ValueError(msg)
