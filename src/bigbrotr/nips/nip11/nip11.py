"""
Top-level NIP-11 model with factory method and database serialization.

Wraps the [Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]
container and provides ``create()`` for retrieving a relay's
[NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md) information
document, and ``to_relay_metadata_tuple()`` for converting the result into
database-ready [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
records.

See Also:
    [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
        The metadata container with HTTP info retrieval capabilities.
    [bigbrotr.models.metadata.Metadata][bigbrotr.models.metadata.Metadata]:
        Content-addressed metadata model used for database storage.
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        The ``NIP11_INFO`` variant used when creating metadata records.
    [bigbrotr.models.relay_metadata.RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]:
        Junction model linking a relay to its metadata.
"""

from __future__ import annotations

from time import time
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.models.relay_metadata import RelayMetadata

from .info import Nip11InfoMetadata


class RelayNip11MetadataTuple(NamedTuple):
    """Database-ready tuple of NIP-11 ``RelayMetadata`` records.

    See Also:
        [Nip11.to_relay_metadata_tuple][bigbrotr.nips.nip11.nip11.Nip11.to_relay_metadata_tuple]:
            Method that produces instances of this tuple.
        [bigbrotr.nips.nip66.nip66.RelayNip66MetadataTuple][bigbrotr.nips.nip66.nip66.RelayNip66MetadataTuple]:
            Companion tuple for NIP-66 metadata records.
    """

    nip11_info: RelayMetadata | None


class Nip11(BaseModel):
    """NIP-11 relay information document.

    Created via the ``create()`` async factory method, which retrieves the
    relay's information document over HTTP and packages the result.

    Attributes:
        relay: The [Relay][bigbrotr.models.relay.Relay] this document belongs to.
        info: Info data and logs (``None`` if retrieval was not attempted).
        generated_at: Unix timestamp of when the document was retrieved.

    Note:
        The ``create()`` factory method **never raises exceptions**. Always
        check ``info.logs.success`` for the operation outcome.
        This design allows batch processing of many relays without individual
        error handling.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            Companion NIP-66 model with the same factory/serialization pattern.
        [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
            Service that calls ``create()`` during health check cycles.

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        nip11 = await Nip11.create(relay, timeout=10.0)
        if nip11.info and nip11.info.logs.success:
            print(nip11.info.data.name)  # 'Damus Relay'
        ```
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    info: Nip11InfoMetadata | None = None
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    # -------------------------------------------------------------------------
    # Database Serialization
    # -------------------------------------------------------------------------

    def to_relay_metadata_tuple(self) -> RelayNip11MetadataTuple:
        """Convert to a ``RelayMetadata`` tuple for database storage.

        Returns:
            A [RelayNip11MetadataTuple][bigbrotr.nips.nip11.nip11.RelayNip11MetadataTuple]
            with the info metadata wrapped in a
            [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] junction
            record tagged as
            [MetadataType.NIP11_INFO][bigbrotr.models.metadata.MetadataType],
            or ``None`` if no info retrieval was performed.
        """
        nip11_info: RelayMetadata | None = None
        if self.info is not None:
            nip11_info = RelayMetadata(
                relay=self.relay,
                metadata=Metadata(
                    type=MetadataType.NIP11_INFO,
                    data=self.info.to_dict(),
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
        """Retrieve a relay's NIP-11 document and return a populated Nip11 instance.

        This method never raises and never returns None. Check
        ``info.logs.success`` for the outcome.

        Args:
            relay: Relay to retrieve from.
            timeout: HTTP request timeout in seconds (default: 10.0).
            max_size: Maximum response body size in bytes (default: 64 KB).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL on certificate
                errors (default: True).

        Returns:
            A new ``Nip11`` instance containing the info results.
        """
        info = await Nip11InfoMetadata.execute(
            relay, timeout, max_size, proxy_url, allow_insecure=allow_insecure
        )
        return cls(relay=relay, info=info)
