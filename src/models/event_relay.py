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
    >>> params = event_relay.to_db_params()  # EventRelayDbParams for insert
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, NamedTuple

from .event import Event


class EventRelayDbParams(NamedTuple):
    """Database parameters for EventRelay insert operations."""

    # Event fields
    event_id: bytes
    pubkey: bytes
    created_at: int
    kind: int
    tags_json: str
    content: str
    sig: bytes
    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Junction field
    seen_at: int


if TYPE_CHECKING:
    from .relay import Relay


@dataclass(frozen=True, slots=True)
class EventRelay:
    """
    Immutable representation of an Event seen on a Relay.

    Attributes:
        event: The wrapped Nostr event
        relay: The relay where the event was seen
        seen_at: Unix timestamp when event was first seen (defaults to now)
    """

    event: Event
    relay: Relay
    seen_at: int = field(default_factory=lambda: int(time()))

    def to_db_params(self) -> EventRelayDbParams:
        """
        Convert to database parameters.

        Returns:
            EventRelayDbParams with named fields for event, relay, and seen_at
        """
        e = self.event.to_db_params()
        r = self.relay.to_db_params()
        return EventRelayDbParams(
            event_id=e.id,
            pubkey=e.pubkey,
            created_at=e.created_at,
            kind=e.kind,
            tags_json=e.tags_json,
            content=e.content,
            sig=e.sig,
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            seen_at=self.seen_at,
        )

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
            relay_url: Relay URL with scheme (e.g., "wss://relay.example.com")
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
