"""
RelayMetadata junction model for BigBrotr.

Represents a time-series snapshot linking a Relay to its Metadata by type.
Used for storing NIP-11 and NIP-66 monitoring data with content-addressed
deduplication (metadata hash computed by PostgreSQL during insertion).

Database mapping:
    - relay_url -> relays.url (FK)
    - generated_at -> relay_metadata.generated_at timestamp
    - type -> MetadataType enum value (nip11, nip66_rtt, nip66_ssl, nip66_geo, nip66_dns, nip66_http)
    - metadata_id -> metadata.id (FK, computed from content hash)

Example:
    >>> relay_metadata = RelayMetadata(
    ...     relay=relay, metadata=Metadata({"name": "My Relay"}), metadata_type="nip11"
    ... )
    >>> params = relay_metadata.to_db_params()  # RelayMetadataDbParams
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time
from typing import NamedTuple

from .metadata import Metadata
from .relay import Relay


class MetadataType(StrEnum):
    """Metadata type constants matching database CHECK constraint."""

    NIP11 = "nip11"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class RelayMetadataDbParams(NamedTuple):
    """Database parameters for RelayMetadata insert operations."""

    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Metadata fields
    metadata_data: str
    # Junction fields
    metadata_type: MetadataType
    generated_at: int


@dataclass(frozen=True, slots=True)
class RelayMetadata:
    """
    Immutable relay metadata junction record.

    Represents a row in the `relay_metadata` table:
    - relay_url: Foreign key to relays.url
    - generated_at: Unix timestamp when metadata was collected
    - type: Metadata type (see MetadataType enum)
    - metadata_id: Foreign key to metadata.id

    Links a Relay to a Metadata object with timestamp and type context.
    """

    relay: Relay
    metadata: Metadata
    metadata_type: MetadataType
    generated_at: int = field(default_factory=lambda: int(time()))

    def to_db_params(self) -> RelayMetadataDbParams:
        """
        Return database parameters for relay_metadata_insert_cascade procedure.

        The metadata hash is computed by PostgreSQL, not Python.

        Returns:
            RelayMetadataDbParams with named fields for relay, metadata, type, and timestamp
        """
        r = self.relay.to_db_params()
        m = self.metadata.to_db_params()
        return RelayMetadataDbParams(
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            metadata_data=m.data_json,
            metadata_type=self.metadata_type,
            generated_at=self.generated_at,
        )

    @classmethod
    def from_db_params(
        cls,
        relay_url: str,
        relay_network: str,
        relay_discovered_at: int,
        metadata_data: str,
        metadata_type: MetadataType,
        generated_at: int,
    ) -> RelayMetadata:
        """
        Create RelayMetadata from database parameters.

        Args:
            relay_url: Relay URL with scheme (e.g., "wss://relay.example.com")
            relay_network: Relay network type
            relay_discovered_at: Relay discovery timestamp
            metadata_data: JSON string of metadata
            metadata_type: MetadataType enum value
            generated_at: When metadata was collected

        Returns:
            RelayMetadata instance
        """
        relay = Relay.from_db_params(relay_url, relay_network, relay_discovered_at)
        metadata = Metadata.from_db_params(metadata_data)
        return cls(
            relay=relay,
            metadata=metadata,
            metadata_type=metadata_type,
            generated_at=generated_at,
        )
