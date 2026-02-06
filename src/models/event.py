"""
Immutable Nostr event wrapper with database serialization.

Wraps ``nostr_sdk.Event`` in a frozen dataclass that transparently delegates
attribute access to the underlying SDK object while adding database conversion
via ``to_db_params()`` and ``from_db_params()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NamedTuple

from nostr_sdk import Event as NostrEvent


class EventDbParams(NamedTuple):
    """Positional parameters for the event database insert procedure."""

    id: bytes
    pubkey: bytes
    created_at: int
    kind: int
    tags: str
    content: str
    sig: bytes


@dataclass(frozen=True, slots=True)
class Event:
    """Immutable Nostr event with database conversion.

    All attribute access is transparently delegated to the inner
    ``nostr_sdk.Event`` via ``__getattr__``, so SDK methods like
    ``id()``, ``kind()``, and ``content()`` work directly.

    Validation is performed eagerly at construction time:

    * Content and tag values are checked for null bytes, which
      PostgreSQL TEXT columns reject.
    * ``to_db_params()`` is called to ensure the event can be
      serialized before it leaves the constructor (fail-fast).

    Args:
        _inner: The underlying ``nostr_sdk.Event`` instance.

    Raises:
        ValueError: If content or tags contain null bytes, or if
            database parameter conversion fails.
    """

    _inner: NostrEvent

    def __post_init__(self) -> None:
        """Validate the event for database compatibility on construction."""
        event_id = self._inner.id().to_hex()[:16]

        if "\x00" in self._inner.content():
            raise ValueError(f"Event {event_id}... content contains null bytes")

        for tag in self._inner.tags().to_vec():
            for value in tag.as_vec():
                if "\x00" in value:
                    raise ValueError(f"Event {event_id}... tags contain null bytes")

        # Ensure DB conversion succeeds at creation time
        self.to_db_params()

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped NostrEvent."""
        return getattr(self._inner, name)

    def to_db_params(self) -> EventDbParams:
        """Convert to positional parameters for the database insert procedure.

        Returns:
            EventDbParams with binary id/pubkey/sig, integer timestamps,
            JSON-encoded tags, and raw content string.
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
        """Reconstruct an Event from database parameters.

        Converts the stored binary/integer fields back into a JSON
        representation that ``nostr_sdk.Event.from_json()`` can parse.

        Args:
            params: Database row values previously produced by ``to_db_params()``.

        Returns:
            A new Event wrapping the reconstructed NostrEvent.
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
