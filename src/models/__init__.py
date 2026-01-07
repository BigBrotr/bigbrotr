"""
BigBrotr Data Models.

First-class types for working with Nostr relays, events, and metadata.

Models:
    - Client: Nostr client wrapper with SSL fallback and proxy support
    - Event: Immutable wrapper for nostr_sdk.Event
    - EventRelay: Junction model linking Event to Relay with seen_at timestamp
    - Relay: Validated Nostr relay URL with network detection
    - Metadata: Content-addressed metadata payload (NIP-11/NIP-66 data)
    - RelayMetadata: Junction linking Relay to Metadata with type and timestamp
    - Nip11: NIP-11 relay information document
    - Nip66: NIP-66 relay monitoring data (RTT, SSL, geo)
    - Keys: Extended Nostr keys with environment variable loading
"""

from .event import Event
from .event_relay import EventRelay
from .keys import Keys
from .metadata import Metadata
from .nip11 import Nip11
from .nip66 import Nip66
from .relay import NetworkType, Relay
from .relay_metadata import MetadataType, RelayMetadata


__all__ = [
    "Event",
    "EventRelay",
    "Keys",
    "Metadata",
    "MetadataType",
    "NetworkType",
    "Nip11",
    "Nip66",
    "Relay",
    "RelayMetadata",
]
