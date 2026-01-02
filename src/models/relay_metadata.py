"""
RelayMetadata junction model for BigBrotr.

Represents a time-series snapshot linking a Relay to its Metadata by type.
Used for storing NIP-11 and NIP-66 monitoring data with content-addressed
deduplication (metadata hash computed by PostgreSQL during insertion).

Database mapping:
    - relay_url -> relays.url (FK)
    - snapshot_at -> generated_at timestamp
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
from typing import Literal, Optional

from .metadata import Metadata
from .relay import Relay


# Valid metadata types matching database CHECK constraint
MetadataType = Literal["nip11", "nip66_rtt", "nip66_ssl", "nip66_geo"]


@dataclass(frozen=True)
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
        generated_at: Optional[int] = None,
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
        generated_at: Optional[int] = None,
    ) -> None:
        """Empty initializer; all initialization is performed in __new__ for frozen dataclass."""

    def to_db_params(self) -> tuple[str, str, int, int, str, str]:
        """
        Return database parameters for insert_relay_metadata procedure.

        The metadata hash is computed by PostgreSQL, not Python.

        Returns:
            Tuple of (relay_url, relay_network, relay_discovered_at,
                     generated_at, metadata_type, metadata_data)
        """
        return (
            self.relay.url_without_scheme,
            self.relay.network,
            self.relay.discovered_at,
            self.generated_at,
            self.metadata_type,
            self.metadata.data_jsonb,
        )
