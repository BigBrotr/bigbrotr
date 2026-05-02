"""
Junction model linking an [Event][bigbrotr.models.event.Event] to the
[Relay][bigbrotr.models.relay.Relay] where it was observed.

Maps to the ``event_observation`` table in the database, recording which
relay an event was received from and when it was first seen there.
The database uses the ``event_observation_insert_cascade`` stored procedure
to atomically insert the relay, event, and junction record in a single call.

See Also:
    [bigbrotr.models.event][]: The [Event][bigbrotr.models.event.Event] model
        wrapped by this junction.
    [bigbrotr.models.relay][]: The [Relay][bigbrotr.models.relay.Relay] model
        wrapped by this junction.
    [bigbrotr.models.relay_document][]: Analogous junction model linking a
        [Relay][bigbrotr.models.relay.Relay] to a
        [Document][bigbrotr.models.document.Document] record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from ._validation import validate_instance, validate_timestamp
from .event import Event
from .relay import Relay


class EventObservationDbParams(NamedTuple):
    """Positional parameters for the event-observation junction insert procedure.

    Combines fields from the [Event][bigbrotr.models.event.Event],
    [Relay][bigbrotr.models.relay.Relay], and the junction timestamp into a
    single flat tuple for the ``event_observation_insert_cascade`` stored procedure.

    Attributes:
        event_id: Event ID as 32-byte binary
            (from [EventDbParams][bigbrotr.models.event.EventDbParams]).
        pubkey: Author public key as 32-byte binary.
        created_at: Unix timestamp of event creation.
        kind: Integer event kind.
        tags: JSON-encoded array of tag arrays.
        content: Raw event content string.
        sig: Schnorr signature as 64-byte binary.
        relay_url: Fully normalized relay WebSocket URL
            (from [RelayDbParams][bigbrotr.models.relay.RelayDbParams]).
        relay_network: Network type string (e.g., ``"clearnet"``, ``"tor"``).
        relay_stored_at: Unix timestamp when the relay entered the canonical stored relay pool.
        observed_at: Unix timestamp when the event was first observed on this relay.

    See Also:
        [EventObservation][bigbrotr.models.event_observation.EventObservation]:
            The model that produces these parameters.
        [EventDbParams][bigbrotr.models.event.EventDbParams]: Source of the event fields.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Source of the relay fields.
    """

    event_id: bytes
    pubkey: bytes
    created_at: int
    kind: int
    tags: str
    content: str
    sig: bytes
    relay_url: str
    relay_network: str
    relay_stored_at: int
    observed_at: int


@dataclass(frozen=True, slots=True)
class EventObservation:
    """Immutable record of an [Event][bigbrotr.models.event.Event] observed on a
    specific [Relay][bigbrotr.models.relay.Relay].

    Attributes:
        event: The Nostr [Event][bigbrotr.models.event.Event] that was observed.
        relay: The [Relay][bigbrotr.models.relay.Relay] where the event was seen.
        observed_at: Unix timestamp of when the event was first seen (defaults to now).

    Examples:
        ```python
        event_observation = EventObservation(event=event, relay=relay)
        event_observation.observed_at       # Auto-set to current time
        params = event_observation.to_db_params()
        params.relay_url          # 'wss://relay.damus.io'
        params.event_id           # Binary event ID (bytes)
        ```

    Note:
        The flat
        [EventObservationDbParams][bigbrotr.models.event_observation.EventObservationDbParams]
        tuple is designed for the ``event_observation_insert_cascade`` stored
        procedure, which atomically inserts the relay, event, and junction
        record. This avoids multiple round-trips and ensures referential
        integrity.

    See Also:
        [Event][bigbrotr.models.event.Event]: The event half of this junction.
        [Relay][bigbrotr.models.relay.Relay]: The relay half of this junction.
        [EventObservationDbParams][bigbrotr.models.event_observation.EventObservationDbParams]:
            Database parameter container produced by
            [to_db_params()][bigbrotr.models.event_observation.EventObservation.to_db_params].
        [RelayDocument][bigbrotr.models.relay_document.RelayDocument]: Analogous
            junction model for relay-to-document associations.
    """

    event: Event
    relay: Relay
    observed_at: int = field(default_factory=lambda: math.ceil(time()))
    _db_params: EventObservationDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate field types and compute database parameters (fail-fast)."""
        validate_instance(self.event, Event, "event")
        validate_instance(self.relay, Relay, "relay")
        validate_timestamp(self.observed_at, "observed_at")
        object.__setattr__(self, "_db_params", self._compute_db_params())

    def _compute_db_params(self) -> EventObservationDbParams:
        """Compute positional parameters for the cascade insert procedure.

        Merges the [EventDbParams][bigbrotr.models.event.EventDbParams] and
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams] from the contained
        models with the junction ``observed_at`` timestamp into a single flat tuple.

        Returns:
            [EventObservationDbParams][bigbrotr.models.event_observation.EventObservationDbParams]
            combining event, relay, and junction fields.
        """
        e = self.event.to_db_params()
        r = self.relay.to_db_params()
        return EventObservationDbParams(
            event_id=e.id,
            pubkey=e.pubkey,
            created_at=e.created_at,
            kind=e.kind,
            tags=e.tags,
            content=e.content,
            sig=e.sig,
            relay_url=r.url,
            relay_network=r.network,
            relay_stored_at=r.stored_at,
            observed_at=self.observed_at,
        )

    def to_db_params(self) -> EventObservationDbParams:
        """Return cached database parameters computed during initialization.

        Returns:
            [EventObservationDbParams][bigbrotr.models.event_observation.EventObservationDbParams]
            combining event, relay, and junction fields.
        """
        return self._db_params
