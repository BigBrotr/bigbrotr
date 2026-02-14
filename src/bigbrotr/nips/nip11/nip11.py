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

import logging
from dataclasses import dataclass
from typing import NamedTuple

from bigbrotr.models.constants import DEFAULT_TIMEOUT
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.models.relay_metadata import RelayMetadata
from bigbrotr.nips.base import (
    BaseNip,
    BaseNipDependencies,
    BaseNipOptions,
    BaseNipSelection,
)

from .info import Nip11InfoMetadata


logger = logging.getLogger("bigbrotr.nips.nip11")


class Nip11Selection(BaseNipSelection):
    """Which NIP-11 metadata to retrieve.

    All retrieval types are enabled by default. Set individual fields to
    ``False`` to skip specific metadata types during
    [Nip11.create][bigbrotr.nips.nip11.nip11.Nip11.create].

    See Also:
        [Nip11Options][bigbrotr.nips.nip11.nip11.Nip11Options]:
            Controls *how* metadata is retrieved (e.g., allow insecure SSL).
        [Nip11Dependencies][bigbrotr.nips.nip11.nip11.Nip11Dependencies]:
            Provides optional dependencies required by specific retrievals.
    """

    info: bool = True


class Nip11Options(BaseNipOptions):
    """How to execute NIP-11 metadata retrieval.

    Inherits ``allow_insecure`` from
    [BaseNipOptions][bigbrotr.nips.base.BaseNipOptions].

    Attributes:
        max_size: Maximum response body size in bytes
            (default: 64 KB from ``Nip11InfoMetadata._INFO_MAX_SIZE``).

    See Also:
        [Nip11Selection][bigbrotr.nips.nip11.nip11.Nip11Selection]:
            Controls *which* metadata is retrieved.
    """

    max_size: int = Nip11InfoMetadata._INFO_MAX_SIZE


@dataclass(frozen=True)
class Nip11Dependencies(BaseNipDependencies):
    """Optional dependencies for NIP-11 metadata retrieval.

    Currently empty. NIP-11 info retrieval requires no external
    resources. Provided for structural parity with
    [Nip66Dependencies][bigbrotr.nips.nip66.nip66.Nip66Dependencies]
    and future extensibility.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66Dependencies][bigbrotr.nips.nip66.nip66.Nip66Dependencies]:
            NIP-66 counterpart with keys, GeoIP readers, etc.
    """


class RelayNip11MetadataTuple(NamedTuple):
    """Database-ready tuple of NIP-11 ``RelayMetadata`` records.

    See Also:
        [Nip11.to_relay_metadata_tuple][bigbrotr.nips.nip11.nip11.Nip11.to_relay_metadata_tuple]:
            Method that produces instances of this tuple.
        [bigbrotr.nips.nip66.nip66.RelayNip66MetadataTuple][bigbrotr.nips.nip66.nip66.RelayNip66MetadataTuple]:
            Companion tuple for NIP-66 metadata records.
    """

    nip11_info: RelayMetadata | None


class Nip11(BaseNip):
    """NIP-11 relay information document.

    Created via the ``create()`` async factory method, which retrieves the
    relay's information document over HTTP and packages the result.

    Attributes:
        relay: The [Relay][bigbrotr.models.relay.Relay] this document belongs to
            (inherited from [BaseNip][bigbrotr.nips.base.BaseNip]).
        info: Info data and logs (``None`` if retrieval was not attempted).
        generated_at: Unix timestamp of when the document was retrieved
            (inherited from [BaseNip][bigbrotr.nips.base.BaseNip]).

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
        selection = Nip11Selection(info=True)
        options = Nip11Options(allow_insecure=True)
        nip11 = await Nip11.create(relay, timeout=10.0, selection=selection, options=options)
        if nip11.info and nip11.info.logs.success:
            print(nip11.info.data.name)  # 'Damus Relay'
        ```
    """

    info: Nip11InfoMetadata | None = None

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
    async def create(  # type: ignore[override]  # noqa: PLR0913
        cls,
        relay: Relay,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        selection: Nip11Selection | None = None,
        options: Nip11Options | None = None,
        deps: Nip11Dependencies | None = None,
    ) -> Nip11:
        """Retrieve a relay's NIP-11 document and return a populated Nip11 instance.

        All retrieval types are enabled by default. Individual types can be
        disabled via the ``selection`` parameter. Execution behavior can be
        tuned via the ``options`` parameter. Some retrievals may require
        additional dependencies in the future, provided via ``deps``.

        This method never raises and never returns None. Check
        ``info.logs.success`` for the outcome.

        Args:
            relay: Relay to retrieve from.
            timeout: HTTP request timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            selection: Which metadata to retrieve (default: all enabled).
            options: How to execute the retrieval (default: secure mode).
            deps: Optional dependencies for future extensibility.

        Returns:
            A new ``Nip11`` instance containing the info results.
        """
        selection = selection or Nip11Selection()
        options = options or Nip11Options()
        deps = deps or Nip11Dependencies()
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("create_started relay=%s timeout_s=%s", relay.url, timeout)

        info = None
        if selection.info:
            info = await Nip11InfoMetadata.execute(
                relay,
                timeout,
                options.max_size,
                proxy_url,
                allow_insecure=options.allow_insecure,
            )

        logger.debug(
            "create_completed relay=%s info=%s",
            relay.url,
            info is not None and info.logs.success if info else False,
        )
        return cls(relay=relay, info=info)
