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

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType


_CURSOR_ID_HEX_LENGTH = 64


def _validate_non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _normalize_cursor_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("id must be a str")
    if len(value) != _CURSOR_ID_HEX_LENGTH:
        raise ValueError("id must be a 64-character hex string")
    try:
        normalized = bytes.fromhex(value).hex()
    except ValueError as exc:
        raise ValueError("id must be a 64-character hex string") from exc
    if len(normalized) != _CURSOR_ID_HEX_LENGTH:
        raise ValueError("id must be a 64-character hex string")
    return normalized


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
        timestamp: Unix timestamp of the last processing event (defaults to 0).
    """

    key: str
    timestamp: int = 0


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


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateCheckpoint(Checkpoint):
    """Checkpoint for relay validation candidates (Validator).

    Tracks candidate relay URLs with a failure counter and network type.
    The ``key`` is the relay URL, ``timestamp`` is the insertion time
    (for new candidates) or last validation attempt time (for retries).

    Created by
    [insert_relays_as_candidates][bigbrotr.services.common.discovery_queries.insert_relays_as_candidates]
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

    def __post_init__(self) -> None:
        relay = Relay(self.key)
        if (
            not isinstance(self.timestamp, int)
            or isinstance(self.timestamp, bool)
            or self.timestamp < 0
        ):
            raise ValueError("timestamp must be a non-negative integer")
        if (
            not isinstance(self.failures, int)
            or isinstance(self.failures, bool)
            or self.failures < 0
        ):
            raise ValueError("failures must be a non-negative integer")
        if not isinstance(self.network, NetworkType):
            raise TypeError("network must be a NetworkType")
        if relay.network != self.network:
            raise ValueError(
                "candidate network "
                f"{self.network.value!r} does not match relay URL network "
                f"{relay.network.value!r}"
            )


@dataclass(frozen=True, slots=True)
class Cursor:
    """Composite pagination cursor stored in ``service_state``.

    Tracks a position within an ordered stream using a ``(timestamp, id)``
    pair for deterministic tie-breaking. Both fields default to sentinel
    values (``0`` and ``"0" * 64``) representing "scan from beginning".

    Subclass per usage to enable type-level disambiguation:

    - [SyncCursor][bigbrotr.services.common.types.SyncCursor]
    - [FinderCursor][bigbrotr.services.common.types.FinderCursor]

    Attributes:
        key: State key identifying the entity (typically a relay URL).
        timestamp: Unix timestamp of the last processed record (default ``0``).
        id: Hex-encoded 64-char event ID for deterministic tie-breaking
            (default ``"0" * 64``).
    """

    key: str
    timestamp: int = 0
    id: str = "0" * 64

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("key must be a str")
        _validate_non_negative_int(self.timestamp, "timestamp")
        object.__setattr__(self, "id", _normalize_cursor_id(self.id))


@dataclass(frozen=True, slots=True)
class SyncCursor(Cursor):
    """Per-relay cursor for event synchronization (Synchronizer).

    Tracks how far event fetching has progressed for a given relay.
    ``timestamp`` is the event ``created_at``, ``id`` is the event ID.
    """

    def __post_init__(self) -> None:
        Cursor.__post_init__(self)
        object.__setattr__(self, "key", Relay(self.key).url)


@dataclass(frozen=True, slots=True)
class FinderCursor(Cursor):
    """Per-relay cursor for event scanning pagination (Finder).

    Tracks how far local event scanning has progressed for a given relay.
    ``timestamp`` is the ``observed_at`` from the ``event_observation`` junction,
    ``id`` is the event ID for tie-breaking.
    """

    def __post_init__(self) -> None:
        Cursor.__post_init__(self)
        object.__setattr__(self, "key", Relay(self.key).url)


@dataclass(frozen=True, slots=True)
class DvmRequestCursor(Cursor):
    """Cursor for NIP-90 request replay protection (Dvm).

    Tracks the newest processed job request using the event ``created_at``
    timestamp and event ID. The ``key`` is the logical DVM request stream
    identifier (currently ``"job_requests"``).
    """
