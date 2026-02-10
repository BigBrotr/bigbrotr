"""Nostr Implementation Possibilities -- protocol-specific fetch and parse logic.

The NIPs layer sits in the middle of the diamond DAG, depending on
`bigbrotr.models` and `bigbrotr.utils`. It performs I/O (HTTP, DNS, SSL,
WebSocket, GeoIP) and is the most protocol-aware part of the codebase.

Warning:
    NIP fetch methods (`Nip11.create()`, `Nip66.create()`) **never raise
    exceptions**. Always check `logs.success` on the returned metadata to
    determine whether the operation succeeded.

Attributes:
    Nip11: Fetches and parses NIP-11 Relay Information Documents via HTTP.
        Converts wss/ws URL to https/http, sends `Accept: application/nostr+json`.
        SSL fallback: clearnet tries verified first, falls back to insecure if
        `allow_insecure=True`; overlay networks always use insecure context.
    Nip66: Orchestrates six parallel health tests per relay: RTT (round-trip
        time), SSL (certificate chain), DNS (A/AAAA/CNAME), Geo (GeoIP location),
        Net (ASN info), HTTP (response headers). Each test produces a separate
        `RelayMetadata` record with the appropriate `MetadataType`.
    BaseData, BaseLogs, BaseMetadata: Shared abstract base classes inherited by
        all NIP data, log, and metadata models.
"""

from bigbrotr.nips.base import BaseData, BaseLogs, BaseMetadata
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import Nip66


__all__ = ["BaseData", "BaseLogs", "BaseMetadata", "Nip11", "Nip66"]
