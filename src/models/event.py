"""
Nostr Event wrapper for BigBrotr.

Provides Event class that wraps nostr_sdk.Event with database conversion.
Uses composition instead of inheritance to avoid fragile PyO3 binding inheritance.
"""

import json
from typing import Any

from nostr_sdk import Event as NostrEvent


def tags_to_list(event: NostrEvent) -> list[list[str]]:
    """
    Convert nostr_sdk event tags to list of lists.

    Shared utility function used by Event and EventRelay.

    Args:
        event: nostr_sdk.Event instance

    Returns:
        List of tag arrays: [["e", "id"], ["p", "pubkey"], ...]
    """
    return [list(tag.as_vec()) for tag in event.tags().to_vec()]


def event_to_db_params(event: NostrEvent) -> tuple[bytes, bytes, int, int, str, str, bytes]:
    """
    Convert nostr_sdk event to database parameters tuple.

    Shared utility function used by Event and EventRelay.

    Args:
        event: nostr_sdk.Event instance

    Returns:
        Tuple of (id, pubkey, created_at, kind, tags_json, content, sig)
    """
    tags = tags_to_list(event)
    return (
        bytes.fromhex(event.id().to_hex()),
        bytes.fromhex(event.author().to_hex()),
        event.created_at().as_secs(),
        event.kind().as_u16(),
        json.dumps(tags),
        event.content(),
        bytes.fromhex(event.signature()),
    )


class Event:
    """
    Immutable Nostr event wrapper.

    Uses composition instead of inheritance to wrap nostr_sdk.Event safely.
    The inner NostrEvent is a Rust/PyO3 binding that may have different behavior
    across versions, so composition provides better stability.

    Attributes:
        _inner: The wrapped nostr_sdk.Event instance
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: NostrEvent) -> None:
        """
        Create Event wrapper from nostr_sdk.Event.

        Args:
            inner: nostr_sdk.Event instance to wrap
        """
        object.__setattr__(self, "_inner", inner)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Event is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Event is immutable")

    # Delegate common methods to inner event
    def id(self):
        """Get event ID."""
        return self._inner.id()

    def author(self):
        """Get event author (pubkey)."""
        return self._inner.author()

    def created_at(self):
        """Get event creation timestamp."""
        return self._inner.created_at()

    def kind(self):
        """Get event kind."""
        return self._inner.kind()

    def tags(self):
        """Get event tags."""
        return self._inner.tags()

    def content(self) -> str:
        """Get event content."""
        return self._inner.content()

    def signature(self) -> str:
        """Get event signature."""
        return self._inner.signature()

    def verify(self) -> bool:
        """Verify event signature."""
        return self._inner.verify()

    def to_db_params(self) -> tuple[bytes, bytes, int, int, str, str, bytes]:
        """
        Convert to database parameters tuple.

        Returns:
            Tuple of (id, pubkey, created_at, kind, tags_json, content, sig)
        """
        return event_to_db_params(self._inner)

    @property
    def inner(self) -> NostrEvent:
        """Access the underlying nostr_sdk.Event."""
        return self._inner
