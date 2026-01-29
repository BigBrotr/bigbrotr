"""NIP-11 main class and database tuple."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from models.metadata import Metadata
from models.relay_metadata import MetadataType, RelayMetadata

from .fetch import Nip11FetchMetadata


if TYPE_CHECKING:
    from models.relay import Relay

    from .logs import Nip11FetchLogs


class RelayNip11MetadataTuple(NamedTuple):
    """Tuple of RelayMetadata records for database storage."""

    nip11_fetch: RelayMetadata


class Nip11(BaseModel):
    """
    Immutable NIP-11 relay information document.

    Fetches relay information via HTTP with Accept: application/nostr+json header.
    Raw JSON is parsed and validated into typed Pydantic models.

    Always created via create() or fetch() - never returns None.
    Check .logs.success for status.

    Attributes:
        relay: The Relay this document belongs to
        fetch_metadata: Container with data and logs (Nip11FetchMetadata model)
        generated_at: Unix timestamp when fetched (default: now, must be >= 0)
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    fetch_metadata: Nip11FetchMetadata
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    # -------------------------------------------------------------------------
    # Convenience Properties (consistent API with NIP-66 metadata classes)
    # -------------------------------------------------------------------------

    @property
    def logs(self) -> Nip11FetchLogs:
        """Delegate to fetch_metadata.logs for consistent API with NIP-66."""
        return self.fetch_metadata.logs

    @property
    def limitation(self) -> dict[str, Any] | None:
        """Get limitation dict or None for backward compatibility.

        Converts the Pydantic model to dict, excluding None values.
        Returns None if no limitations are set.
        """
        lim = self.fetch_metadata.data.limitation
        if lim is None:
            return None
        result = {k: v for k, v in lim.model_dump().items() if v is not None}
        return result or None

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip11MetadataTuple:
        """Convert to RelayNip11MetadataTuple for database storage."""
        return RelayNip11MetadataTuple(
            nip11_fetch=RelayMetadata(
                relay=self.relay,
                metadata=Metadata(self.fetch_metadata.to_dict()),
                metadata_type=MetadataType.NIP11_FETCH,
                generated_at=self.generated_at,
            ),
        )

    def to_relay_metadata(self) -> RelayMetadata:
        """Convert to single RelayMetadata for database storage.

        Convenience method that returns the nip11_fetch record directly.
        """
        return self.to_relay_metadata_tuple().nip11_fetch

    @classmethod
    async def create(
        cls,
        relay: Relay,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip11:
        """
        Fetch NIP-11 document from relay.

        Convenience wrapper around Nip11FetchMetadata.fetch() that returns a full Nip11 instance.

        Always returns Nip11 - never raises, never None.
        Check .logs.success for fetch status.

        Args:
            relay: Relay to fetch from
            timeout: Request timeout in seconds (default: 10.0)
            max_size: Max response size in bytes (default: 64KB)
            proxy_url: Optional SOCKS5 proxy URL
            allow_insecure: Fallback to insecure on cert errors (default: True)

        Returns:
            Nip11 instance - check .logs.success for status

        Example::

            nip11 = await Nip11.create(relay)
            if nip11.logs.success:
                print(f"Name: {nip11.fetch_metadata.data.name}")
            else:
                print(f"Failed: {nip11.logs.reason}")
        """
        fetch_metadata = await Nip11FetchMetadata.fetch(
            relay, timeout, max_size, proxy_url, allow_insecure
        )
        return cls(relay=relay, fetch_metadata=fetch_metadata)

    @classmethod
    async def fetch(
        cls,
        relay: Relay,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip11:
        """Alias for create() - consistent naming with NIP-66 metadata classes."""
        return await cls.create(relay, timeout, max_size, proxy_url, allow_insecure)
