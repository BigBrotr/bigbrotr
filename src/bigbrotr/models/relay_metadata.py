"""
Junction model linking a Relay to a Metadata record.

Maps to the ``relay_metadata`` table, representing a time-series snapshot
that associates a relay with a specific metadata payload. Metadata records
are deduplicated via content-addressed hashing (SHA-256 computed in Python).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from .metadata import Metadata, MetadataDbParams, MetadataType
from .relay import Relay, RelayDbParams


class RelayMetadataDbParams(NamedTuple):
    """Positional parameters for the relay-metadata junction insert procedure.

    Attributes:
        relay_url: Relay WebSocket URL.
        relay_network: Network type string (clearnet, tor, i2p, loki).
        relay_discovered_at: Unix timestamp of relay discovery.
        metadata_id: SHA-256 content hash (32 bytes).
        metadata_value: Canonical JSON string for JSONB storage.
        metadata_type: Metadata type discriminator.
        generated_at: Unix timestamp when the metadata was collected.
    """

    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Metadata fields
    metadata_id: bytes
    metadata_value: str
    # Junction fields
    metadata_type: MetadataType
    generated_at: int


@dataclass(frozen=True, slots=True)
class RelayMetadata:
    """Immutable junction record linking a Relay to a Metadata payload.

    The ``metadata_type`` is carried by the ``Metadata`` object and written
    to the junction table to allow type-filtered queries.

    Attributes:
        relay: The relay this metadata belongs to.
        metadata: The metadata payload (with type and content hash).
        generated_at: Unix timestamp when the metadata was collected (defaults to now).
    """

    relay: Relay
    metadata: Metadata
    generated_at: int = field(default_factory=lambda: int(time()))
    _db_params: RelayMetadataDbParams | None = field(
        default=None, init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        """Validate database parameter conversion at construction time (fail-fast)."""
        object.__setattr__(self, "_db_params", self._compute_db_params())

    def to_db_params(self) -> RelayMetadataDbParams:
        """Convert to positional parameters for the cascade insert procedure.

        Returns:
            RelayMetadataDbParams combining relay, metadata, and junction fields.
        """
        return self._db_params  # type: ignore[return-value]

    def _compute_db_params(self) -> RelayMetadataDbParams:
        """Convert to positional parameters for the cascade insert procedure.

        Returns:
            RelayMetadataDbParams combining relay, metadata, and junction fields.
        """
        r = self.relay.to_db_params()
        m = self.metadata.to_db_params()
        return RelayMetadataDbParams(
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            metadata_id=m.id,
            metadata_value=m.value,
            metadata_type=m.metadata_type,
            generated_at=self.generated_at,
        )

    @classmethod
    def from_db_params(cls, params: RelayMetadataDbParams) -> RelayMetadata:
        """Reconstruct a RelayMetadata from database parameters.

        Args:
            params: Database row values previously produced by ``to_db_params()``.

        Returns:
            A new RelayMetadata instance.

        Raises:
            ValueError: If the metadata content hash does not match (integrity check).
        """
        relay_params = RelayDbParams(
            url=params.relay_url,
            network=params.relay_network,
            discovered_at=params.relay_discovered_at,
        )
        metadata_params = MetadataDbParams(
            id=params.metadata_id,
            value=params.metadata_value,
            metadata_type=params.metadata_type,
        )
        relay = Relay.from_db_params(relay_params)
        metadata = Metadata.from_db_params(metadata_params)
        return cls(
            relay=relay,
            metadata=metadata,
            generated_at=params.generated_at,
        )
