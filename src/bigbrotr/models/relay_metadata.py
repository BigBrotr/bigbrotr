"""
Junction model linking a [Relay][bigbrotr.models.relay.Relay] to a
[Metadata][bigbrotr.models.metadata.Metadata] record.

Maps to the ``relay_metadata`` table, representing a time-series snapshot
that associates a relay with a specific metadata payload. Metadata records
are deduplicated via content-addressed hashing (SHA-256 computed in Python).
The database uses the ``relay_metadata_insert_cascade`` stored procedure
to atomically insert the relay, metadata, and junction record in a single call.

See Also:
    [bigbrotr.models.relay][]: The [Relay][bigbrotr.models.relay.Relay] model
        wrapped by this junction.
    [bigbrotr.models.metadata][]: The [Metadata][bigbrotr.models.metadata.Metadata]
        model wrapped by this junction.
    [bigbrotr.models.event_relay][]: Analogous junction model linking a
        [Relay][bigbrotr.models.relay.Relay] to an
        [Event][bigbrotr.models.event.Event].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from .metadata import Metadata, MetadataDbParams, MetadataType
from .relay import Relay, RelayDbParams


class RelayMetadataDbParams(NamedTuple):
    """Positional parameters for the relay-metadata junction insert procedure.

    Produced by
    [RelayMetadata.to_db_params()][bigbrotr.models.relay_metadata.RelayMetadata.to_db_params]
    and consumed by the ``relay_metadata_insert_cascade`` stored procedure
    in PostgreSQL.

    Attributes:
        relay_url: Relay WebSocket URL (from [RelayDbParams][bigbrotr.models.relay.RelayDbParams]).
        relay_network: Network type string (e.g., ``"clearnet"``, ``"tor"``).
        relay_discovered_at: Unix timestamp of relay discovery.
        metadata_id: SHA-256 content hash (32 bytes,
            from [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams]).
        metadata_payload: Canonical JSON string for JSONB storage.
        metadata_type: [MetadataType][bigbrotr.models.metadata.MetadataType] discriminator.
        generated_at: Unix timestamp when the metadata was collected.

    See Also:
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: The model that
            produces these parameters.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Source of the relay fields.
        [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams]: Source of the
            metadata fields.
    """

    # Relay fields
    relay_url: str
    relay_network: str
    relay_discovered_at: int
    # Metadata fields
    metadata_id: bytes
    metadata_payload: str
    # Junction fields
    metadata_type: MetadataType
    generated_at: int


@dataclass(frozen=True, slots=True)
class RelayMetadata:
    """Immutable junction linking a [Relay][bigbrotr.models.relay.Relay] to a
    [Metadata][bigbrotr.models.metadata.Metadata] payload.

    The [MetadataType][bigbrotr.models.metadata.MetadataType] is carried by the
    [Metadata][bigbrotr.models.metadata.Metadata] object and written to the
    junction table to allow type-filtered queries.

    Attributes:
        relay: The [Relay][bigbrotr.models.relay.Relay] this metadata belongs to.
        metadata: The [Metadata][bigbrotr.models.metadata.Metadata] payload
            (with type and content hash).
        generated_at: Unix timestamp when the metadata was collected (defaults to now).

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        meta = Metadata(type=MetadataType.NIP11_INFO, value={"name": "Damus"})
        rm = RelayMetadata(relay=relay, metadata=meta)
        rm.generated_at       # Auto-set to current time
        params = rm.to_db_params()
        params.relay_url      # 'wss://relay.damus.io'
        params.metadata_type  # MetadataType.NIP11_INFO
        ```

    Note:
        The ``metadata_type`` is denormalized onto the junction table
        (``relay_metadata``) even though it also exists on the
        [Metadata][bigbrotr.models.metadata.Metadata] object. This allows
        efficient type-filtered queries (e.g., "latest NIP-11 info for all
        relays") without joining through the ``metadata`` table.

    See Also:
        [Relay][bigbrotr.models.relay.Relay]: The relay half of this junction.
        [Metadata][bigbrotr.models.metadata.Metadata]: The metadata half of this
            junction.
        [MetadataType][bigbrotr.models.metadata.MetadataType]: Enum of metadata
            classifications used for filtering.
        [RelayMetadataDbParams][bigbrotr.models.relay_metadata.RelayMetadataDbParams]:
            Database parameter container produced by
            [to_db_params()][bigbrotr.models.relay_metadata.RelayMetadata.to_db_params].
        [EventRelay][bigbrotr.models.event_relay.EventRelay]: Analogous junction
            model for event-to-relay associations.
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
        """Return cached positional parameters for the cascade insert procedure.

        Returns:
            [RelayMetadataDbParams][bigbrotr.models.relay_metadata.RelayMetadataDbParams]
            combining relay, metadata, and junction fields.
        """
        assert self._db_params is not None  # noqa: S101  # Always set in __post_init__
        return self._db_params

    def _compute_db_params(self) -> RelayMetadataDbParams:
        """Compute positional parameters for the cascade insert procedure.

        Merges the [RelayDbParams][bigbrotr.models.relay.RelayDbParams] and
        [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams] from the
        contained models with the junction ``generated_at`` timestamp and
        ``metadata_type`` into a single flat tuple.

        Returns:
            [RelayMetadataDbParams][bigbrotr.models.relay_metadata.RelayMetadataDbParams]
            combining relay, metadata, and junction fields.
        """
        r = self.relay.to_db_params()
        m = self.metadata.to_db_params()
        return RelayMetadataDbParams(
            relay_url=r.url,
            relay_network=r.network,
            relay_discovered_at=r.discovered_at,
            metadata_id=m.id,
            metadata_payload=m.payload,
            metadata_type=m.metadata_type,
            generated_at=self.generated_at,
        )

    @classmethod
    def from_db_params(cls, params: RelayMetadataDbParams) -> RelayMetadata:
        """Reconstruct a ``RelayMetadata`` from database parameters.

        Args:
            params: Database row values previously produced by
                [to_db_params()][bigbrotr.models.relay_metadata.RelayMetadata.to_db_params].

        Returns:
            A new [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] instance.

        Raises:
            ValueError: If the metadata content hash does not match (integrity
                check performed by
                [Metadata.from_db_params()][bigbrotr.models.metadata.Metadata.from_db_params]).

        Note:
            Both the [Relay][bigbrotr.models.relay.Relay] and
            [Metadata][bigbrotr.models.metadata.Metadata] are fully re-validated
            during reconstruction. The relay URL is re-parsed and the metadata
            hash is recomputed and verified against the stored value.
        """
        relay_params = RelayDbParams(
            url=params.relay_url,
            network=params.relay_network,
            discovered_at=params.relay_discovered_at,
        )
        metadata_params = MetadataDbParams(
            id=params.metadata_id,
            payload=params.metadata_payload,
            metadata_type=params.metadata_type,
        )
        relay = Relay.from_db_params(relay_params)
        metadata = Metadata.from_db_params(metadata_params)
        return cls(
            relay=relay,
            metadata=metadata,
            generated_at=params.generated_at,
        )
