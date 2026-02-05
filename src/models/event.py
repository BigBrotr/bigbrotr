"""
Nostr Event wrapper for BigBrotr.

Provides Event class that wraps nostr_sdk.Event with database conversion.
Uses frozen dataclass with __getattr__ delegation to transparently proxy all NostrEvent methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NamedTuple

from nostr_sdk import Event as NostrEvent


class EventDbParams(NamedTuple):
    """Database parameters for Event insert operations."""

    id: bytes
    pubkey: bytes
    created_at: int
    kind: int
    tags: str
    content: str
    sig: bytes


@dataclass(frozen=True, slots=True)
class Event:
    """
    Immutable Nostr event wrapper with database conversion.

    Frozen dataclass that transparently proxies all NostrEvent methods via
    __getattr__ and adds to_db_params() for database insertion.

    Note:
        Like all Python frozen dataclasses, immutability is enforced at the
        normal API level. Direct calls to object.__setattr__() can bypass
        this, but such usage is explicitly discouraged.

    Example:
        >>> event = Event(nostr_event)
        >>> event.id()  # Delegated to nostr_event
        >>> event.to_db_params()  # Added method
    """

    _inner: NostrEvent

    def __post_init__(self) -> None:
        """Validate event for database compatibility.

        Also validates that to_db_params() succeeds, ensuring the model
        is database-ready at creation time (fail-fast).

        Raises:
            ValueError: If content or tags contain null bytes (PostgreSQL rejects them)
                       or if to_db_params() conversion fails.
        """
        event_id = self._inner.id().to_hex()[:16]

        # Check content for null bytes
        if "\x00" in self._inner.content():
            raise ValueError(f"Event {event_id}... content contains null bytes")

        # Check tags for null bytes
        for tag in self._inner.tags().to_vec():
            for value in tag.as_vec():
                if "\x00" in value:
                    raise ValueError(f"Event {event_id}... tags contain null bytes")

        # Validate database params conversion (fail-fast)
        self.to_db_params()

    def __getattr__(self, name: str) -> Any:
        """Delegate all attribute access to the wrapped NostrEvent."""
        return getattr(self._inner, name)

    def to_db_params(self) -> EventDbParams:
        """
        Convert to database parameters tuple.

        Returns:
            EventDbParams with named fields: id, pubkey, created_at, kind, tags, content, sig
        """
        inner = self._inner
        tags_list = [list(tag.as_vec()) for tag in inner.tags().to_vec()]
        return EventDbParams(
            id=bytes.fromhex(inner.id().to_hex()),
            pubkey=bytes.fromhex(inner.author().to_hex()),
            created_at=inner.created_at().as_secs(),
            kind=inner.kind().as_u16(),
            tags=json.dumps(tags_list),
            content=inner.content(),
            sig=bytes.fromhex(inner.signature()),
        )

    @classmethod
    def from_db_params(cls, params: EventDbParams) -> Event:
        """
        Create an Event from database parameters.

        Args:
            params: EventDbParams containing id, pubkey, created_at, kind,
                    tags, content, and sig fields.

        Returns:
            Event instance wrapping a reconstructed NostrEvent
        """
        tags = json.loads(params.tags)
        inner = NostrEvent.from_json(
            json.dumps(
                {
                    "id": params.id.hex(),
                    "pubkey": params.pubkey.hex(),
                    "created_at": params.created_at,
                    "kind": params.kind,
                    "tags": tags,
                    "content": params.content,
                    "sig": params.sig.hex(),
                }
            )
        )
        return cls(inner)
