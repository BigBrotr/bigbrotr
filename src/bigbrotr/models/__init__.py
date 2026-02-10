"""Pure frozen dataclasses with zero I/O for Nostr relays, events, and metadata.

The models layer is the foundation of the diamond DAG. It has **no dependencies**
on any other BigBrotr package -- only the Python standard library. Every model uses
`@dataclass(frozen=True, slots=True)` for immutability and memory efficiency.

Database parameter containers use `NamedTuple` and are cached in `__post_init__`
to avoid repeated conversions. All validation happens in `__post_init__` so
invalid instances never escape the constructor.

NIP models (`Nip11`, `Nip66`) are in the separate `bigbrotr.nips` package.

Attributes:
    Relay: Validated Nostr relay URL with RFC 3986 parsing and automatic network
        type detection (clearnet, Tor, I2P, Lokinet). Rejects local IPs.
    Event: Immutable wrapper around `nostr_sdk.Event` with BYTEA encoding for
        binary fields (ID, pubkey, sig) and fail-fast DB conversion.
    EventRelay: Junction linking an Event to the Relay where it was observed,
        with cascade insert support for atomic multi-table writes.
    Metadata: Content-addressed metadata payload with SHA-256 hashing.
        Supports seven `MetadataType` values (nip11_info, nip66_rtt, etc.).
    RelayMetadata: Junction linking a Relay to a Metadata record via
        content-addressed hashing, with cascade insert support.
    ServiceState: Cursor-based processing state for pipeline services,
        enabling resume after restart.
    NetworkType: Enum classifying relay URLs into clearnet, tor, i2p, loki,
        local, or unknown.
"""

from .constants import NetworkType
from .event import Event
from .event_relay import EventRelay
from .metadata import Metadata, MetadataType
from .relay import Relay
from .relay_metadata import RelayMetadata
from .service_state import (
    EVENT_KIND_MAX,
    EventKind,
    ServiceState,
    ServiceStateKey,
    StateType,
)


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
    "ServiceState",
    "ServiceStateKey",
    "StateType",
]
