"""
RelayMetadata junction model for BigBrotr.

Represents a time-series snapshot linking a Relay to its Metadata by type.
Used for storing NIP-11 and NIP-66 monitoring data with content-addressed
deduplication (metadata hash computed by PostgreSQL during insertion).

Database mapping:
    - relay_url -> relays.url (FK)
    - generated_at -> relay_metadata.generated_at timestamp
    - type -> 'nip11', 'nip66_rtt', 'nip66_ssl', or 'nip66_geo'
    - metadata_id -> metadata.id (FK, computed from content hash)

Example:
    >>> relay_metadata = RelayMetadata(
    ...     relay=relay, metadata=Metadata({"name": "My Relay"}), metadata_type="nip11"
    ... )
    >>> params = relay_metadata.to_db_params()
"""

from dataclasses import dataclass
from time import time
from typing import Literal

from .metadata import Metadata
from .relay import Relay


# Valid metadata types matching database CHECK constraint
MetadataType = Literal["nip11", "nip66_rtt", "nip66_ssl", "nip66_geo"]


@dataclass(frozen=True, slots=True)
class RelayMetadata:
    """
    Immutable relay metadata junction record.

    Represents a row in the `relay_metadata` table:
    - relay_url: Foreign key to relays.url
    - generated_at: Unix timestamp when metadata was collected
    - type: Metadata type ('nip11', 'nip66_rtt', 'nip66_geo')
    - metadata_id: Foreign key to metadata.id

    Links a Relay to a Metadata object with timestamp and type context.
    """

    relay: Relay
    metadata: Metadata
    metadata_type: MetadataType
    generated_at: int

    def __new__(
        cls,
        relay: Relay,
        metadata: Metadata,
        metadata_type: MetadataType,
        generated_at: int | None = None,
    ) -> "RelayMetadata":
        instance = object.__new__(cls)
        object.__setattr__(instance, "relay", relay)
        object.__setattr__(instance, "metadata", metadata)
        object.__setattr__(instance, "metadata_type", metadata_type)
        object.__setattr__(
            instance, "generated_at", generated_at if generated_at is not None else int(time())
        )
        return instance

    def __init__(
        self,
        relay: Relay,
        metadata: Metadata,
        metadata_type: MetadataType,
        generated_at: int | None = None,
    ) -> None:
        """Empty initializer; all initialization is performed in __new__ for frozen dataclass."""

    def to_db_params(self) -> tuple[str, str, int, str, str, int]:
        """
        Return database parameters for relay_metadata_insert_cascade procedure.

        The metadata hash is computed by PostgreSQL, not Python.

        Returns:
            Tuple of:
            - relay_url: Relay URL without scheme
            - relay_network: Relay network type
            - relay_discovered_at: Relay discovery timestamp
            - metadata_data: JSON string of metadata
            - metadata_type: Type of metadata ('nip11', 'nip66_rtt', etc.)
            - generated_at: When metadata was collected
        """
        return (
            self.relay.to_db_params()
            + self.metadata.to_db_params()
            + (self.metadata_type, self.generated_at)
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
    ) -> "RelayMetadata":
        """
        Create RelayMetadata from database parameters.

        Args:
            relay_url: Relay URL without scheme
            relay_network: Relay network type
            relay_discovered_at: Relay discovery timestamp
            metadata_data: JSON string of metadata
            metadata_type: Type of metadata ('nip11', 'nip66_rtt', etc.)
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
