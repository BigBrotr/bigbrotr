"""
EventRelay junction model for BigBrotr.

Represents an Event seen on a specific Relay at a specific time.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Optional, Union

from .event import event_to_db_params
from .relay import Relay

if TYPE_CHECKING:
    from nostr_sdk import Event as NostrEvent

    from .event import Event


@dataclass(frozen=True)
class EventRelay:
    """
    Immutable representation of an Event seen on a Relay.

    Attributes:
        event: The Nostr event (Event wrapper or raw NostrEvent)
        relay: The relay where the event was seen
        seen_at: Unix timestamp when event was first seen
    """

    event: Union[Event, NostrEvent]
    relay: Relay
    seen_at: int

    def __new__(
        cls, event: Union[Event, NostrEvent], relay: Relay, seen_at: Optional[int] = None
    ):
        instance = object.__new__(cls)
        object.__setattr__(instance, "event", event)
        object.__setattr__(instance, "relay", relay)
        object.__setattr__(instance, "seen_at", seen_at if seen_at is not None else int(time()))
        return instance

    def __init__(
        self, event: Union[Event, NostrEvent], relay: Relay, seen_at: Optional[int] = None
    ):
        pass

    @classmethod
    def from_nostr_event(
        cls, event: NostrEvent, relay: Relay, seen_at: Optional[int] = None
    ) -> EventRelay:
        """
        Create EventRelay from a nostr_sdk Event and Relay.

        Args:
            event: nostr_sdk Event object received from relay
            relay: Relay where the event was seen
            seen_at: Unix timestamp when event was seen (defaults to now)

        Returns:
            EventRelay instance
        """
        return cls(event=event, relay=relay, seen_at=seen_at)

    def _event_to_db_params(self) -> tuple:
        """
        Extract database parameters from event.

        Uses shared event_to_db_params function to avoid code duplication.
        Works with both Event wrapper and raw NostrEvent.
        """
        evt = self.event

        # If it's our Event wrapper, use its to_db_params
        if hasattr(evt, "to_db_params") and callable(getattr(evt, "to_db_params", None)):
            return evt.to_db_params()

        # If it's an Event wrapper with inner, get the inner NostrEvent
        if hasattr(evt, "inner"):
            return event_to_db_params(evt.inner)

        # Otherwise it's a raw NostrEvent - use the shared function
        return event_to_db_params(evt)

    def to_db_params(self) -> tuple:
        """
        Convert to database parameters tuple.

        Returns:
            Tuple of (e_id, e_pubkey, e_created_at, e_kind, e_tags, e_content, e_sig,
                      r_url, r_network, r_discovered_at, er_seen_at)
        """
        return self._event_to_db_params() + self.relay.to_db_params() + (self.seen_at,)
