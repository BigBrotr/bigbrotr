"""
Immutable Nostr event wrapper with database serialization.

Accepts a ``nostr_sdk.Event`` at construction, eagerly extracts all fields
into Python-native types, and releases the FFI reference.  The underlying
``NostrEvent`` is consumed during construction and NOT retained, preventing
Rust-side memory from accumulating across event processing pipelines.

See Also:
    [bigbrotr.models.event_relay][]: Junction model linking an
        [Event][bigbrotr.models.event.Event] to the
        [Relay][bigbrotr.models.relay.Relay] where it was observed.
    [bigbrotr.services.synchronizer][]: The service that collects events from
        relays and persists them via this model.
"""

from __future__ import annotations

import json
from dataclasses import InitVar, dataclass, field
from typing import ClassVar, NamedTuple

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

    Accepts a ``nostr_sdk.Event`` at construction, validates it for
    database compatibility, extracts all fields into Python-native types,
    and releases the FFI reference.  The underlying ``NostrEvent`` is NOT
    retained after construction -- all domain data lives in regular Python
    fields, consistent with every other model in this package.

    Validation is performed eagerly at construction time:

    * Content and tag values are checked for null bytes, which
      PostgreSQL TEXT columns reject.
    * [to_db_params()][bigbrotr.models.event.Event.to_db_params] is called
      to ensure the event can be serialized before it leaves the constructor
      (fail-fast).

    Args:
        event: The ``nostr_sdk.Event`` to extract data from.
            Consumed during construction and not retained.

    Raises:
        ValueError: If content or tags contain null bytes, or if
            database parameter conversion fails.

    Note:
        Domain fields store protocol-native representations: hex strings
        for ``id``, ``pubkey``, and ``sig``; integer seconds for
        ``created_at``; integer kind; raw ``content`` string; and an
        immutable tuple-of-tuples for ``tags``.  Binary conversions
        (``bytes.fromhex``) and JSON serialization (``json.dumps``)
        happen once in ``_compute_db_params`` and are cached.

        Equality and hashing are based on the domain fields
        (``id``, ``pubkey``, ``created_at``, ``kind``).  Fields with
        ``compare=False`` (``tags``, ``content``, ``sig``) are excluded
        because ``id`` is already the SHA-256 of the full event content.

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

    event: InitVar[NostrEvent]

    id: str = field(init=False)
    pubkey: str = field(init=False)
    created_at: int = field(init=False)
    kind: int = field(init=False)
    tags: tuple[tuple[str, ...], ...] = field(init=False, repr=False, compare=False)
    content: str = field(init=False, repr=False, compare=False)
    sig: str = field(init=False, repr=False, compare=False)
    _db_params: EventDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]
    )

    _MAX_TAG_VALUE_LENGTH: ClassVar[int] = 2048

    def __post_init__(self, event: NostrEvent) -> None:
        """Validate the event and extract all fields from the FFI object."""
        validate_instance(event, NostrEvent, "event")

        event_id = event.id().to_hex()
        object.__setattr__(self, "id", event_id)
        object.__setattr__(self, "pubkey", event.author().to_hex())
        object.__setattr__(self, "created_at", event.created_at().as_secs())
        object.__setattr__(self, "kind", event.kind().as_u16())
        object.__setattr__(self, "sig", event.signature())

        content = event.content()
        if "\x00" in content:
            raise ValueError(f"Event {event_id[:16]}... content contains null bytes")
        object.__setattr__(self, "content", content)

        tags_list: list[tuple[str, ...]] = []
        for tag in event.tags().to_vec():
            values = tag.as_vec()
            for value in values:
                if "\x00" in value:
                    raise ValueError(f"Event {event_id[:16]}... tags contain null bytes")
                if len(value) > Event._MAX_TAG_VALUE_LENGTH:
                    raise ValueError(
                        f"Event {event_id[:16]}... tag value exceeds "
                        f"{Event._MAX_TAG_VALUE_LENGTH} chars ({len(value)})"
                    )
            tags_list.append(tuple(values))
        object.__setattr__(self, "tags", tuple(tags_list))

        object.__setattr__(self, "_db_params", self._compute_db_params())

    def _compute_db_params(self) -> EventDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache.  Domain fields store protocol-native representations (hex
        strings, tuples); this method performs the one-time conversion to
        database types (binary bytes, JSON strings).

        Returns:
            [EventDbParams][bigbrotr.models.event.EventDbParams] with binary
            id/pubkey/sig, integer timestamps, JSON-encoded tags, and raw
            content string.
        """
        return EventDbParams(
            id=bytes.fromhex(self.id),
            pubkey=bytes.fromhex(self.pubkey),
            created_at=self.created_at,
            kind=self.kind,
            tags=json.dumps([list(t) for t in self.tags]),
            content=self.content,
            sig=bytes.fromhex(self.sig),
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
