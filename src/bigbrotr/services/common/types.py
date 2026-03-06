"""Shared domain types for BigBrotr services.

Lightweight dataclasses produced by query functions and consumed by
services.  Keeping them in their own module avoids circular imports
between ``queries`` and individual service packages.

Each ``ServiceStateType`` has a corresponding typed class:

- **CHECKPOINT** → [Checkpoint][bigbrotr.services.common.types.Checkpoint]
  (with subclasses [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint],
  [MonitorCheckpoint][bigbrotr.services.common.types.MonitorCheckpoint],
  [PublishCheckpoint][bigbrotr.services.common.types.PublishCheckpoint],
  [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint])
- **CURSOR** → [Cursor][bigbrotr.services.common.types.Cursor]
  (with subclasses [SyncCursor][bigbrotr.services.common.types.SyncCursor],
  [FinderCursor][bigbrotr.services.common.types.FinderCursor])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.models.constants import NetworkType


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Timestamp-based progress marker stored in ``service_state``.

    Represents a CHECKPOINT record: a named key with a Unix timestamp
    tracking when the associated entity was last processed.

    Subclass per usage to enable type-level disambiguation:

    - [ApiCheckpoint][bigbrotr.services.common.types.ApiCheckpoint]
    - [MonitorCheckpoint][bigbrotr.services.common.types.MonitorCheckpoint]
    - [PublishCheckpoint][bigbrotr.services.common.types.PublishCheckpoint]
    - [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint]

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
class CandidateCheckpoint(Checkpoint):
    """Checkpoint for relay validation candidates (Validator).

    Tracks candidate relay URLs with a failure counter and network type.
    The ``key`` is the relay URL, ``timestamp`` is the insertion time
    (for new candidates) or last validation attempt time (for retries).

    Created by
    [insert_relays_as_candidates][bigbrotr.services.validator.queries.insert_relays_as_candidates]
    and fetched by
    [fetch_candidates][bigbrotr.services.validator.queries.fetch_candidates].

    Attributes:
        key: Relay URL (inherited from Checkpoint).
        timestamp: Unix timestamp of creation or last attempt (inherited).
        network: [NetworkType][bigbrotr.models.constants.NetworkType] of
            the candidate relay.
        failures: Number of failed validation attempts (0 for new candidates).
    """

    network: NetworkType
    failures: int = 0


@dataclass(frozen=True, slots=True)
class Cursor:
    """Composite pagination cursor stored in ``service_state``.

    Tracks a position within an ordered stream using a ``(timestamp, id)``
    pair for deterministic tie-breaking. Both fields must be ``None``
    (new cursor, scan from beginning) or both set (resumption point).

    Subclass per usage to enable type-level disambiguation:

    - [SyncCursor][bigbrotr.services.common.types.SyncCursor]
    - [FinderCursor][bigbrotr.services.common.types.FinderCursor]

    Attributes:
        key: State key identifying the entity (typically a relay URL).
        timestamp: Unix timestamp of the last processed record, or None.
        id: Raw 32-byte ID for deterministic tie-breaking, or None.
    """

    key: str
    timestamp: int | None = None
    id: bytes | None = None

    def __post_init__(self) -> None:
        if (self.timestamp is None) != (self.id is None):
            msg = "timestamp and id must both be None or both be set"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SyncCursor(Cursor):
    """Per-relay cursor for event synchronization (Synchronizer).

    Tracks how far event fetching has progressed for a given relay.
    ``timestamp`` is the event ``created_at``, ``id`` is the event ID.
    """


@dataclass(frozen=True, slots=True)
class FinderCursor(Cursor):
    """Per-relay cursor for event scanning pagination (Finder).

    Tracks how far local event scanning has progressed for a given relay.
    ``timestamp`` is the ``seen_at`` from the ``event_relay`` junction,
    ``id`` is the event ID for tie-breaking.
    """
