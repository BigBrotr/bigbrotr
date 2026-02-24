"""
Immutable Nostr event wrapper with database serialization.

Wraps ``nostr_sdk.Event`` in a frozen dataclass that transparently delegates
attribute access to the underlying SDK object while adding database conversion
via [to_db_params()][bigbrotr.models.event.Event.to_db_params] and
[from_db_params()][bigbrotr.models.event.Event.from_db_params].

See Also:
    [bigbrotr.models.event_relay][]: Junction model linking an
        [Event][bigbrotr.models.event.Event] to the
        [Relay][bigbrotr.models.relay.Relay] where it was observed.
    [bigbrotr.services.synchronizer][]: The service that collects events from
        relays and persists them via this model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from nostr_sdk import Event as NostrEvent

from ._validation import validate_instance


class EventDbParams(NamedTuple):
    """Positional parameters for the event database insert procedure.

    Produced by [Event.to_db_params()][bigbrotr.models.event.Event.to_db_params]
    and consumed by the ``event_insert`` stored procedure in PostgreSQL.

    Attributes:
        id: Event ID as 32-byte binary (SHA-256 of the serialized event).
        pubkey: Author public key as 32-byte binary.
        created_at: Unix timestamp of event creation.
        kind: Integer event kind (e.g., 1 for text notes, 10002 for relay lists).
        tags: JSON-encoded array of tag arrays.
        content: Raw event content string.
        sig: Schnorr signature as 64-byte binary.

    See Also:
        [Event][bigbrotr.models.event.Event]: The model that produces these parameters.
        [Event.from_db_params()][bigbrotr.models.event.Event.from_db_params]: Reconstructs
            an [Event][bigbrotr.models.event.Event] from these parameters.
        [EventRelayDbParams][bigbrotr.models.event_relay.EventRelayDbParams]: Extends
            these fields with relay and junction data for cascade inserts.
    """

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
    * [to_db_params()][bigbrotr.models.event.Event.to_db_params] is called
      to ensure the event can be serialized before it leaves the constructor
      (fail-fast).

    Args:
        _nostr_event: The underlying ``nostr_sdk.Event`` instance.

    Raises:
        ValueError: If content or tags contain null bytes, or if
            database parameter conversion fails.

    Examples:
        ```python
        from nostr_sdk import Event as NostrEvent

        nostr_event = NostrEvent.from_json('{"id": "ab...", ...}')
        event = Event(nostr_event)
        event.id()         # Delegates to nostr_sdk.Event
        event.content()    # Delegates to nostr_sdk.Event
        params = event.to_db_params()
        params.kind        # Integer event kind (e.g. 1)
        ```

    Note:
        Binary fields (``id``, ``pubkey``, ``sig``) are stored as ``bytes``
        in [EventDbParams][bigbrotr.models.event.EventDbParams] for direct
        insertion into PostgreSQL BYTEA columns. The hex-to-bytes conversion
        happens once during ``__post_init__`` and is cached.

        The ``__getattr__`` delegation means this class does **not** define
        ``id``, ``kind``, ``content``, etc. as attributes -- they are resolved
        at runtime from the wrapped ``nostr_sdk.Event``.

    See Also:
        [EventDbParams][bigbrotr.models.event.EventDbParams]: Database parameter
            container produced by
            [to_db_params()][bigbrotr.models.event.Event.to_db_params].
        [EventRelay][bigbrotr.models.event_relay.EventRelay]: Junction linking
            this event to the [Relay][bigbrotr.models.relay.Relay] where it was
            observed.
        [EventKind][bigbrotr.models.constants.EventKind]: Well-known Nostr
            event kinds used across services.
    """

    _nostr_event: NostrEvent
    _db_params: EventDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate the event for database compatibility on construction."""
        validate_instance(self._nostr_event, NostrEvent, "_nostr_event")
        event_id = self._nostr_event.id().to_hex()[:16]

        if "\x00" in self._nostr_event.content():
            raise ValueError(f"Event {event_id}... content contains null bytes")

        for tag in self._nostr_event.tags().to_vec():
            for value in tag.as_vec():
                if "\x00" in value:
                    raise ValueError(f"Event {event_id}... tags contain null bytes")

        object.__setattr__(self, "_db_params", self._compute_db_params())

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the wrapped NostrEvent."""
        try:
            return getattr(self._nostr_event, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from None

    def _compute_db_params(self) -> EventDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through
        [to_db_params()][bigbrotr.models.event.Event.to_db_params].

        Returns:
            [EventDbParams][bigbrotr.models.event.EventDbParams] with binary
            id/pubkey/sig, integer timestamps, JSON-encoded tags, and raw
            content string.
        """
        inner = self._nostr_event
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

    def to_db_params(self) -> EventDbParams:
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance, avoiding repeated hex conversions
        and tag serialization.

        Returns:
            [EventDbParams][bigbrotr.models.event.EventDbParams] with binary
            id/pubkey/sig, integer timestamps, JSON-encoded tags, and raw
            content string.
        """
        return self._db_params

    @classmethod
    def from_db_params(cls, params: EventDbParams) -> Event:
        """Reconstruct an [Event][bigbrotr.models.event.Event] from database parameters.

        Converts the stored binary/integer fields back into a JSON
        representation that ``nostr_sdk.Event.from_json()`` can parse.

        Args:
            params: Database row values previously produced by
                [to_db_params()][bigbrotr.models.event.Event.to_db_params].

        Returns:
            A new [Event][bigbrotr.models.event.Event] wrapping the
            reconstructed ``nostr_sdk.Event``.

        Note:
            The reconstructed event passes through ``__post_init__`` validation
            again, including null-byte checks and DB parameter caching, ensuring
            consistency regardless of the data source.
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
