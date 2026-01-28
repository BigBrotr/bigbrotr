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
    tags_json: str
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
        """Validate event content for database compatibility.

        Raises:
            ValueError: If content contains null bytes (PostgreSQL rejects them).
        """
        if "\x00" in self._inner.content():
            raise ValueError(
                f"Event {self._inner.id().to_hex()[:16]}... content contains null bytes"
            )

    def __getattr__(self, name: str) -> Any:
        """Delegate all attribute access to the wrapped NostrEvent."""
        return getattr(self._inner, name)

    def to_db_params(self) -> EventDbParams:
        """
        Convert to database parameters tuple.

        Returns:
            EventDbParams with named fields: id, pubkey, created_at, kind, tags_json, content, sig
        """
        inner = self._inner
        tags = [list(tag.as_vec()) for tag in inner.tags().to_vec()]
        return EventDbParams(
            id=bytes.fromhex(inner.id().to_hex()),
            pubkey=bytes.fromhex(inner.author().to_hex()),
            created_at=inner.created_at().as_secs(),
            kind=inner.kind().as_u16(),
            tags_json=json.dumps(tags),
            content=inner.content(),
            sig=bytes.fromhex(inner.signature()),
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
    ) -> Event:
        """
        Create an Event from database parameters.

        Args:
            event_id: Event ID as bytes (32 bytes)
            pubkey: Author public key as bytes (32 bytes)
            created_at: Unix timestamp
            kind: Event kind number
            tags_json: JSON string of tags array
            content: Event content
            sig: Signature as bytes (64 bytes)

        Returns:
            Event instance wrapping a reconstructed NostrEvent
        """
        tags = json.loads(tags_json)
        inner = NostrEvent.from_json(
            json.dumps(
                {
                    "id": event_id.hex(),
                    "pubkey": pubkey.hex(),
                    "created_at": created_at,
                    "kind": kind,
                    "tags": tags,
                    "content": content,
                    "sig": sig.hex(),
                }
            )
        )
        return cls(inner)
