"""
Data models for Nostr relays, events, and metadata.

This package provides the core domain types used throughout BigBrotr for
representing Nostr protocol entities and their database mappings:

    Event           Immutable wrapper around nostr_sdk.Event with DB conversion.
    EventRelay      Junction linking an Event to the Relay where it was seen.
    Relay           Validated Nostr relay URL with network type detection.
    Metadata        Content-addressed metadata payload with SHA-256 hashing.
    RelayMetadata   Junction linking a Relay to a Metadata record.
    Nip11           NIP-11 relay information document (fetched via HTTP).
    Nip66           NIP-66 relay monitoring data (RTT, SSL, GEO, DNS, HTTP, NET).

NetworkType is defined in ``utils.network`` and re-exported here for convenience.
"""

from utils.network import NetworkType

from .event import Event
from .event_relay import EventRelay
from .metadata import Metadata, MetadataType
from .nips.nip11 import Nip11
from .nips.nip66 import Nip66
from .relay import Relay
from .relay_metadata import RelayMetadata


__all__ = [
    "Event",
    "EventRelay",
    "Metadata",
    "MetadataType",
    "NetworkType",
    "Nip11",
    "Nip66",
    "Relay",
    "RelayMetadata",
]
