"""
Top-level NIP-11 model with factory method and database serialization.

Wraps the ``Nip11InfoMetadata`` container and provides ``create()`` for
fetching a relay's information document, and ``to_relay_metadata_tuple()``
for converting the result into database-ready ``RelayMetadata`` records.
"""

from __future__ import annotations

from time import time
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.models.relay_metadata import RelayMetadata

from .fetch import Nip11InfoMetadata


class RelayNip11MetadataTuple(NamedTuple):
    """Database-ready tuple of NIP-11 RelayMetadata records."""

    nip11_info: RelayMetadata | None


class Nip11(BaseModel):
    """NIP-11 relay information document.

    Created via the ``create()`` async factory method, which fetches the
    relay's information document over HTTP and packages the result.

    Attributes:
        relay: The relay this document belongs to.
        fetch_metadata: Fetch data and logs (None if fetch was not attempted).
        generated_at: Unix timestamp of when the document was fetched.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    fetch_metadata: Nip11InfoMetadata | None = None
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    # -------------------------------------------------------------------------
    # Database Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip11MetadataTuple:
        """Convert to a tuple of RelayMetadata records for database storage.

        Returns:
            A ``RelayNip11MetadataTuple`` with the fetch metadata wrapped in
            a ``RelayMetadata`` junction record, or ``None`` if no fetch was performed.
        """
        nip11_info: RelayMetadata | None = None
        if self.fetch_metadata is not None:
            nip11_info = RelayMetadata(
                relay=self.relay,
                metadata=Metadata(
                    type=MetadataType.NIP11_INFO,
                    value=self.fetch_metadata.to_dict(),
                ),
                generated_at=self.generated_at,
            )
        return RelayNip11MetadataTuple(nip11_info=nip11_info)

    # -------------------------------------------------------------------------
    # Factory Method
    # -------------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Nip11:
        """Fetch a relay's NIP-11 document and return a populated Nip11 instance.

        This method never raises and never returns None. Check
        ``fetch_metadata.logs.success`` for the outcome.

        Args:
            relay: Relay to fetch from.
            timeout: HTTP request timeout in seconds (default: 10.0).
            max_size: Maximum response body size in bytes (default: 64 KB).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL on certificate
                errors (default: True).

        Returns:
            A new ``Nip11`` instance containing the fetch results.
        """
        fetch_metadata = await Nip11InfoMetadata.execute(
            relay, timeout, max_size, proxy_url, allow_insecure
        )
        return cls(relay=relay, fetch_metadata=fetch_metadata)
