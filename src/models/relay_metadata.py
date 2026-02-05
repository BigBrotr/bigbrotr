"""
RelayMetadata junction model for BigBrotr.

Represents a time-series snapshot linking a Relay to its Metadata.
Used for storing NIP-11 and NIP-66 monitoring data with content-addressed
deduplication (metadata hash computed in Python for determinism).

Database mapping:
    - relay_url -> relays.url (FK)
    - generated_at -> relay_metadata.generated_at timestamp
    - metadata_type -> metadata.type (from Metadata object)
    - metadata_id -> metadata.id (FK, SHA-256 hash computed in Python)

Example:
    >>> from models.metadata import Metadata, MetadataType
    >>> metadata = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "My Relay"})
    >>> relay_metadata = RelayMetadata(relay=relay, metadata=metadata)
    >>> params = relay_metadata.to_db_params()  # RelayMetadataDbParams
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from .metadata import Metadata, MetadataDbParams, MetadataType
from .relay import Relay, RelayDbParams


class RelayMetadataDbParams(NamedTuple):
    """Database parameters for RelayMetadata insert operations.

    Attributes:
        relay_url: Relay WebSocket URL.
        relay_network: Network type (clearnet, tor, i2p, lokinet).
        relay_discovered_at: Unix timestamp when relay was discovered.
        metadata_id: SHA-256 hash (32 bytes) computed in Python.
        metadata_value: Canonical JSON string for JSONB storage.
        metadata_type: Type of metadata (nip11_fetch, nip66_*, etc.).
        generated_at: Unix timestamp when metadata was collected.
    """

    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Metadata fields (hash computed in Python)
    metadata_id: bytes
    metadata_value: str
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
    - metadata_type: From metadata.type (see MetadataType enum)
    - metadata_id: Foreign key to metadata.id

    Links a Relay to a Metadata object with timestamp context.
    The metadata type is stored in the Metadata object itself.
    """

    relay: Relay
    metadata: Metadata
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
            metadata_id=m.id,
            metadata_value=m.value,
            metadata_type=m.type,
            generated_at=self.generated_at,
        )

    @classmethod
    def from_db_params(cls, params: RelayMetadataDbParams) -> RelayMetadata:
        """
        Create RelayMetadata from database parameters.

        Args:
            params: RelayMetadataDbParams containing all relay, metadata, and junction fields.

        Returns:
            RelayMetadata instance

        Raises:
            ValueError: If the metadata hash doesn't match (from Metadata.from_db_params).
        """
        relay_params = RelayDbParams(
            url=params.relay_url,
            network=params.relay_network,
            discovered_at=params.relay_discovered_at,
        )
        metadata_params = MetadataDbParams(
            id=params.metadata_id,
            value=params.metadata_value,
            type=params.metadata_type,
        )
        relay = Relay.from_db_params(relay_params)
        metadata = Metadata.from_db_params(metadata_params)
        return cls(
            relay=relay,
            metadata=metadata,
            generated_at=params.generated_at,
        )
