"""Nostr Implementation Possibilities -- protocol-specific fetch and parse logic.

The NIPs layer sits in the middle of the diamond DAG, depending on
[bigbrotr.models][bigbrotr.models] and [bigbrotr.utils][bigbrotr.utils].
It performs I/O (HTTP, DNS, SSL, WebSocket, GeoIP) and is the most
protocol-aware part of the codebase.

Warning:
    NIP semantic entrypoints ([Nip11.fetch()][bigbrotr.nips.nip11.nip11.Nip11.fetch],
    [Nip66.probe()][bigbrotr.nips.nip66.nip66.Nip66.probe]) **never raise
    exceptions**. Always check ``succeeded`` and ``failure_reason`` on the
    returned metadata to determine whether the operation succeeded.

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
    BaseNip: Abstract base class for top-level NIP models with ``relay``
        and ``generated_at`` plus semantic ``fetch()`` / ``probe()``
        entrypoints on concrete subclasses.
    BaseNipSelection: Base for selection models controlling which metadata types
        to retrieve.
    BaseNipOptions: Base for options models controlling how metadata is retrieved
        (provides the common ``allow_insecure`` option).
    BaseNipDependencies: Base for dependency containers holding external objects
        (keys, database readers) required by specific NIP tests.
    NIP_REGISTRY: Static registry of built-in NIP capability bundles, including
        the top-level models for NIP-11 and NIP-66 plus the event-builder-only
        NIP-85 capability surface.

See Also:
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        Enum with ``NIP11_INFO``, ``NIP66_RTT``, ``NIP66_SSL``, ``NIP66_GEO``,
        ``NIP66_NET``, ``NIP66_DNS``, ``NIP66_HTTP`` variants.
    [bigbrotr.models.metadata.Metadata][bigbrotr.models.metadata.Metadata]:
        Content-addressed metadata model that wraps NIP results for storage.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that orchestrates NIP-11 and NIP-66 checks per relay.
"""

import importlib


__all__ = [
    "NIP_REGISTRY",
    "Nip11",
    "Nip66",
    "NipEntry",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "NIP_REGISTRY": ("bigbrotr.nips.registry", "NIP_REGISTRY"),
    "Nip11": ("bigbrotr.nips.nip11", "Nip11"),
    "Nip66": ("bigbrotr.nips.nip66", "Nip66"),
    "NipEntry": ("bigbrotr.nips.registry", "NipEntry"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'bigbrotr.nips' has no attribute {name!r}")


def __dir__() -> list[str]:
    return __all__
