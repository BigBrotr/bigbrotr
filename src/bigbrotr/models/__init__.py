"""Pure frozen dataclasses with zero I/O for Nostr relays, events, and metadata.

The models layer is the foundation of the diamond DAG. It has **no dependencies**
on any other BigBrotr package -- only the Python standard library. Every model uses
``@dataclass(frozen=True, slots=True)`` for immutability and memory efficiency.

Database parameter containers use ``NamedTuple`` and are cached in ``__post_init__``
to avoid repeated conversions. All validation happens in ``__post_init__`` so
invalid instances never escape the constructor.

NIP models (``Nip11``, ``Nip66``) are in the separate ``bigbrotr.nips`` package.

Attributes:
    Relay: Validated Nostr relay URL with RFC 3986 parsing and automatic
        [NetworkType][bigbrotr.models.constants.NetworkType] detection
        (clearnet, Tor, I2P, Lokinet). Rejects local IPs.
    Event: Immutable wrapper around ``nostr_sdk.Event`` with BYTEA encoding for
        binary fields (ID, pubkey, sig) and fail-fast DB conversion.
    EventRelay: Junction linking an [Event][bigbrotr.models.event.Event] to the
        [Relay][bigbrotr.models.relay.Relay] where it was observed, with cascade
        insert support for atomic multi-table writes.
    Metadata: Content-addressed metadata with SHA-256 hashing.
        Supports seven [MetadataType][bigbrotr.models.metadata.MetadataType]
        values (nip11_info, nip66_rtt, etc.).
    RelayMetadata: Junction linking a [Relay][bigbrotr.models.relay.Relay] to a
        [Metadata][bigbrotr.models.metadata.Metadata] record via
        content-addressed hashing, with cascade insert support.
    ServiceState: Cursor-based processing state for services,
        enabling resume after restart.
    NetworkType: Enum classifying relay URLs into clearnet, tor, i2p, loki,
        local, or unknown.

Note:
    All models use ``object.__setattr__`` in ``__post_init__`` to set computed
    fields on frozen dataclasses. This is the standard workaround for frozen
    dataclass initialization and is safe because ``__post_init__`` runs during
    ``__init__`` before the instance is exposed to external code.

See Also:
    [bigbrotr.models.relay][]: Relay URL validation and network detection.
    [bigbrotr.models.event][]: Nostr event wrapper with database serialization.
    [bigbrotr.models.event_relay][]: Event-to-relay junction model.
    [bigbrotr.models.metadata][]: Content-addressed metadata with SHA-256 hashing.
    [bigbrotr.models.relay_metadata][]: Relay-to-metadata junction model.
    [bigbrotr.models.service_state][]: Service state persistence types.
    [bigbrotr.models.constants][]: Shared constants and enumerations.
    [bigbrotr.nips][]: NIP-11 and NIP-66 models (separate package with I/O).
"""

from .constants import EVENT_KIND_MAX, EventKind, NetworkType, ServiceName
from .event import Event
from .event_relay import EventRelay
from .metadata import Metadata, MetadataType
from .relay import Relay
from .relay_metadata import RelayMetadata
from .service_state import ServiceState, ServiceStateDbParams, ServiceStateType


__all__ = [
    "EVENT_KIND_MAX",
    "Event",
    "EventKind",
    "EventRelay",
    "Metadata",
    "MetadataType",
    "NetworkType",
    "Relay",
    "RelayMetadata",
    "ServiceName",
    "ServiceState",
    "ServiceStateDbParams",
    "ServiceStateType",
]
