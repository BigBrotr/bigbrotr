"""
Junction model linking an Event to the Relay where it was observed.

Maps to the ``events_relays`` table in the database, recording which
relay an event was received from and when it was first seen there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from .event import Event, EventDbParams
from .relay import Relay, RelayDbParams


class EventRelayDbParams(NamedTuple):
    """Positional parameters for the event-relay junction insert procedure.

    Combines fields from the event, relay, and the junction timestamp
    into a single flat tuple for the database stored procedure.
    """

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
    """Immutable record of an Event observed on a specific Relay.

    Attributes:
        event: The Nostr event that was observed.
        relay: The relay where the event was seen.
        seen_at: Unix timestamp of when the event was first seen (defaults to now).
    """

    event: Event
    relay: Relay
    seen_at: int = field(default_factory=lambda: int(time()))

    def __post_init__(self) -> None:
        """Validate database parameter conversion at construction time (fail-fast)."""
        self.to_db_params()

    def to_db_params(self) -> EventRelayDbParams:
        """Convert to positional parameters for the database insert procedure.

        Returns:
            EventRelayDbParams combining event, relay, and junction fields.
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
        """Reconstruct an EventRelay from database parameters.

        Splits the flat parameter tuple back into separate Event and Relay
        instances via their respective ``from_db_params()`` methods.

        Args:
            params: Database row values previously produced by ``to_db_params()``.

        Returns:
            A new EventRelay instance.
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
