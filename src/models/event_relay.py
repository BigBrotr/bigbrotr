"""
EventRelay junction model for BigBrotr.

Represents an Event seen on a specific Relay at a specific time, mapping to
the `events_relays` junction table in the database. This model enables tracking
of event provenance (which relay an event was received from and when).

Database mapping:
    - event_id -> events.id (FK)
    - relay_url -> relays.url (FK)
    - seen_at -> timestamp when event was first seen on this relay

Example:
    >>> from models import Event, EventRelay, Relay
    >>> event_relay = EventRelay(Event(nostr_event), relay)
    >>> params = (
    ...     event_relay.to_db_params()
    ... )  # For events_relays_insert_cascade procedure
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING

from .event import Event


if TYPE_CHECKING:
    from .relay import Relay


@dataclass(frozen=True, slots=True)
class EventRelay:
    """
    Immutable representation of an Event seen on a Relay.

    Attributes:
        event: The wrapped Nostr event
        relay: The relay where the event was seen
        seen_at: Unix timestamp when event was first seen
    """

    event: Event
    relay: Relay
    seen_at: int

    def __new__(cls, event: Event, relay: Relay, seen_at: int | None = None) -> EventRelay:
        instance = object.__new__(cls)
        object.__setattr__(instance, "event", event)
        object.__setattr__(instance, "relay", relay)
        object.__setattr__(instance, "seen_at", seen_at if seen_at is not None else int(time()))
        return instance

    def __init__(self, event: Event, relay: Relay, seen_at: int | None = None) -> None:
        """Empty initializer; all initialization is performed in __new__ for frozen dataclass."""

    def to_db_params(
        self,
    ) -> tuple[bytes, bytes, int, int, str, str, bytes, str, str, int, int]:
        """
        Convert to database parameters tuple.

        Returns:
            Tuple of (e_id, e_pubkey, e_created_at, e_kind, e_tags, e_content, e_sig,
                      r_url, r_network, r_discovered_at, er_seen_at)
        """
        return self.event.to_db_params() + self.relay.to_db_params() + (self.seen_at,)

    @classmethod
    def from_db_params(
        cls,
        event_id: bytes,
        pubkey: bytes,
        created_at: int,
        kind: int,
        tags_json: str,
        content: str,
        sig: bytes,
        relay_url: str,
        relay_network: str,
        relay_discovered_at: int,
        seen_at: int,
    ) -> EventRelay:
        """
        Create an EventRelay from database parameters.

        Args:
            event_id: Event ID as bytes
            pubkey: Author public key as bytes
            created_at: Event creation timestamp
            kind: Event kind number
            tags_json: JSON string of tags array
            content: Event content
            sig: Signature as bytes
            relay_url: Relay URL without scheme
            relay_network: Relay network type
            relay_discovered_at: Relay discovery timestamp
            seen_at: When event was seen on relay

        Returns:
            EventRelay instance
        """
        from .relay import Relay  # noqa: PLC0415

        event = Event.from_db_params(event_id, pubkey, created_at, kind, tags_json, content, sig)
        relay = Relay.from_db_params(relay_url, relay_network, relay_discovered_at)
        return cls(event, relay, seen_at)
