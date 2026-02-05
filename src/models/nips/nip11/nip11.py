"""NIP-11 main class and database tuple."""

from __future__ import annotations

from time import time
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from models.metadata import Metadata, MetadataType
from models.relay import Relay
from models.relay_metadata import RelayMetadata

from .fetch import Nip11FetchMetadata


class RelayNip11MetadataTuple(NamedTuple):
    """Tuple of RelayMetadata records for database storage."""

    nip11_fetch: RelayMetadata | None


class Nip11(BaseModel):
    """
    Immutable NIP-11 relay information document.

    Fetches relay information via HTTP with Accept: application/nostr+json header.
    Raw JSON is parsed and validated into typed Pydantic models.

    Always created via create() - never returns None.
    Check individual metadata fields for availability.

    Attributes:
        relay: The Relay this document belongs to.
        fetch_metadata: Container with data and logs (optional, from HTTP fetch).
        generated_at: Unix timestamp when created (default: now, must be >= 0).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    fetch_metadata: Nip11FetchMetadata | None = None
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip11MetadataTuple:
        """Convert to RelayNip11MetadataTuple for database storage."""
        nip11_fetch: RelayMetadata | None = None
        if self.fetch_metadata is not None:
            nip11_fetch = RelayMetadata(
                relay=self.relay,
                metadata=Metadata(
                    type=MetadataType.NIP11_FETCH,
                    value=self.fetch_metadata.to_dict(),
                ),
                generated_at=self.generated_at,
            )
        return RelayNip11MetadataTuple(nip11_fetch=nip11_fetch)

    # -------------------------------------------------------------------------
    # Factory Method
    # -------------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip11:
        """
        Create NIP-11 data by fetching relay information document.

        Always returns Nip11 - never raises, never None.
        Check individual metadata fields for availability.

        Args:
            relay: Relay to fetch from.
            timeout: Request timeout in seconds (default: 10.0).
            max_size: Max response size in bytes (default: 64KB).
            proxy_url: Optional SOCKS5 proxy URL.
            allow_insecure: Fallback to insecure on cert errors (default: True).

        Returns:
            Nip11 instance with fetch results.

        Example::

            nip11 = await Nip11.create(relay)
            if nip11.fetch_metadata and nip11.fetch_metadata.logs.success:
                print(f"Name: {nip11.fetch_metadata.data.name}")
        """
        fetch_metadata = await Nip11FetchMetadata.fetch(
            relay, timeout, max_size, proxy_url, allow_insecure
        )
        return cls(relay=relay, fetch_metadata=fetch_metadata)
