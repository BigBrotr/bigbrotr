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
from typing import NamedTuple

from .event import Event, EventDbParams
from .relay import Relay, RelayDbParams


class EventRelayDbParams(NamedTuple):
    """Database parameters for EventRelay insert operations."""

    # Event fields
    event_id: bytes
    pubkey: bytes
    created_at: int
    kind: int
    tags: str
    content: str
    sig: bytes
    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Junction field
    seen_at: int


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

    def __post_init__(self) -> None:
        """Validate that to_db_params() succeeds (fail-fast)."""
        self.to_db_params()

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
            tags=e.tags,
            content=e.content,
            sig=e.sig,
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            seen_at=self.seen_at,
        )

    @classmethod
    def from_db_params(cls, params: EventRelayDbParams) -> EventRelay:
        """
        Create an EventRelay from database parameters.

        Args:
            params: EventRelayDbParams containing all event, relay, and junction fields.

        Returns:
            EventRelay instance

        Example::

            params = EventRelayDbParams(
                event_id=b"...",
                pubkey=b"...",
                created_at=1234567890,
                kind=1,
                tags="[]",
                content="test",
                sig=b"...",
                relay_url="wss://relay.example.com",
                relay_network="clearnet",
                relay_discovered_at=1234567890,
                seen_at=9999999999,
            )
            event_relay = EventRelay.from_db_params(params)
        """
        event_params = EventDbParams(
            id=params.event_id,
            pubkey=params.pubkey,
            created_at=params.created_at,
            kind=params.kind,
            tags=params.tags,
            content=params.content,
            sig=params.sig,
        )
        relay_params = RelayDbParams(
            url=params.relay_url,
            network=params.relay_network,
            discovered_at=params.relay_discovered_at,
        )
        event = Event.from_db_params(event_params)
        relay = Relay.from_db_params(relay_params)
        return cls(event, relay, params.seen_at)
