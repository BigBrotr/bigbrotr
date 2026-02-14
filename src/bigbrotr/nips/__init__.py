"""Nostr Implementation Possibilities -- protocol-specific fetch and parse logic.

The NIPs layer sits in the middle of the diamond DAG, depending on
[bigbrotr.models][bigbrotr.models] and [bigbrotr.utils][bigbrotr.utils].
It performs I/O (HTTP, DNS, SSL, WebSocket, GeoIP) and is the most
protocol-aware part of the codebase.

Warning:
    NIP fetch methods ([Nip11.create()][bigbrotr.nips.nip11.nip11.Nip11.create],
    [Nip66.create()][bigbrotr.nips.nip66.nip66.Nip66.create]) **never raise
    exceptions**. Always check ``logs.success`` on the returned metadata to
    determine whether the operation succeeded.

Attributes:
    Nip11: Fetches and parses NIP-11 Relay Information Documents via HTTP.
        Converts wss/ws URL to https/http, sends ``Accept: application/nostr+json``.
        SSL fallback: clearnet tries verified first, falls back to insecure if
        ``allow_insecure=True``; overlay networks always use insecure context.
    Nip66: Orchestrates six parallel health tests per relay: RTT (round-trip
        time), SSL (certificate chain), DNS (A/AAAA/CNAME), Geo (GeoIP location),
        Net (ASN info), HTTP (response headers). Each test produces a separate
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] record
        with the appropriate [MetadataType][bigbrotr.models.metadata.MetadataType].
    BaseData, BaseLogs, BaseNipMetadata: Shared abstract base classes inherited by
        all NIP data, log, and metadata models.
    BaseNip: Abstract base class for top-level NIP models with ``relay``,
        ``generated_at``, and enforced ``create()`` / ``to_relay_metadata_tuple()``
        contract.
    BaseNipSelection: Base for selection models controlling which metadata types
        to retrieve.
    BaseNipOptions: Base for options models controlling how metadata is retrieved
        (provides the common ``allow_insecure`` option).

See Also:
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        Enum with ``NIP11_INFO``, ``NIP66_RTT``, ``NIP66_SSL``, ``NIP66_GEO``,
        ``NIP66_NET``, ``NIP66_DNS``, ``NIP66_HTTP`` variants.
    [bigbrotr.models.metadata.Metadata][bigbrotr.models.metadata.Metadata]:
        Content-addressed metadata model that wraps NIP results for storage.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that orchestrates NIP-11 and NIP-66 checks per relay.
"""

from bigbrotr.nips.base import (
    BaseData,
    BaseLogs,
    BaseNip,
    BaseNipMetadata,
    BaseNipOptions,
    BaseNipSelection,
)
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import Nip66


__all__ = [
    "BaseData",
    "BaseLogs",
    "BaseNip",
    "BaseNipMetadata",
    "BaseNipOptions",
    "BaseNipSelection",
    "Nip11",
    "Nip66",
]
