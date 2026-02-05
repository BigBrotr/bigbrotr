"""
RelayMetadata junction model for BigBrotr.

Represents a time-series snapshot linking a Relay to its Metadata by type.
Used for storing NIP-11 and NIP-66 monitoring data with content-addressed
deduplication (metadata hash computed in Python for determinism).

Database mapping:
    - relay_url -> relays.url (FK)
    - generated_at -> relay_metadata.generated_at timestamp
    - type -> MetadataType enum value
      (nip11_fetch, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http)
    - metadata_id -> metadata.id (FK, SHA-256 hash computed in Python)

Example:
    >>> relay_metadata = RelayMetadata(
    ...     relay=relay,
    ...     metadata=Metadata({"name": "My Relay"}),
    ...     metadata_type="nip11_fetch",
    ... )
    >>> params = relay_metadata.to_db_params()  # RelayMetadataDbParams
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time
from typing import NamedTuple

from .metadata import Metadata, MetadataDbParams
from .relay import Relay, RelayDbParams


class MetadataType(StrEnum):
    """Metadata type constants matching database CHECK constraint.

    Supported types:
        - nip11_fetch: NIP-11 relay information document (HTTP fetch)
        - nip66_rtt: NIP-66 round-trip time measurements
        - nip66_ssl: NIP-66 SSL certificate information
        - nip66_geo: NIP-66 geolocation data
        - nip66_net: NIP-66 network information
        - nip66_dns: NIP-66 DNS resolution data
        - nip66_http: NIP-66 HTTP header information
    """

    NIP11_FETCH = "nip11_fetch"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class RelayMetadataDbParams(NamedTuple):
    """Database parameters for RelayMetadata insert operations.

    Attributes:
        relay_url: Relay WebSocket URL.
        relay_network: Network type (clearnet, tor, i2p, lokinet).
        relay_discovered_at: Unix timestamp when relay was discovered.
        metadata_id: SHA-256 hash (32 bytes) computed in Python.
        metadata_json: Canonical JSON string for JSONB storage.
        metadata_type: Type of metadata (nip11_fetch, nip66_*, etc.).
        generated_at: Unix timestamp when metadata was collected.
    """

    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Metadata fields (hash computed in Python)
    metadata_id: bytes
    metadata_json: str
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

    def __post_init__(self) -> None:
        """Validate that to_db_params() succeeds (fail-fast)."""
        self.to_db_params()

    def to_db_params(self) -> RelayMetadataDbParams:
        """
        Return database parameters for relay_metadata_insert_cascade procedure.

        The metadata hash (SHA-256) is computed in Python for deterministic
        deduplication across all environments.

        Returns:
            RelayMetadataDbParams with named fields for relay, metadata (with hash),
            type, and timestamp.
        """
        r = self.relay.to_db_params()
        m = self.metadata.to_db_params()
        return RelayMetadataDbParams(
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            metadata_id=m.metadata_id,
            metadata_json=m.metadata_json,
            metadata_type=self.metadata_type,
            generated_at=self.generated_at,
        )

    @classmethod
    def from_db_params(cls, params: RelayMetadataDbParams) -> RelayMetadata:
        """
        Create RelayMetadata from database parameters.

        Args:
            params: RelayMetadataDbParams containing all relay, metadata, and junction fields.
                    The metadata_id is not used (hash is recomputed if needed).

        Returns:
            RelayMetadata instance
        """
        relay_params = RelayDbParams(
            url=params.relay_url,
            network=params.relay_network,
            discovered_at=params.relay_discovered_at,
        )
        metadata_params = MetadataDbParams(
            metadata_id=params.metadata_id,
            metadata_json=params.metadata_json,
        )
        relay = Relay.from_db_params(relay_params)
        metadata = Metadata.from_db_params(metadata_params)
        return cls(
            relay=relay,
            metadata=metadata,
            metadata_type=params.metadata_type,
            generated_at=params.generated_at,
        )
