"""Protocol-aware NIP helpers, fetchers, builders, and the static capability registry.

The NIPs layer sits in the middle of the diamond DAG, depending on
[bigbrotr.models][bigbrotr.models] and [bigbrotr.utils][bigbrotr.utils].
It performs protocol-facing work such as HTTP, DNS, SSL, WebSocket, and GeoIP
access and is the most Nostr-aware part of the codebase.

Warning:
    NIP semantic entrypoints ([Nip11.fetch()][bigbrotr.nips.nip11.nip11.Nip11.fetch],
    [Nip66.probe()][bigbrotr.nips.nip66.nip66.Nip66.probe]) **never raise
    exceptions**. Always check ``succeeded`` and ``failure_reason`` on the
    returned result object to determine whether the operation succeeded.

Public exports:
    Nip11: Fetches and parses NIP-11 Relay Information Documents via HTTP.
        Converts wss/ws URL to https/http, sends ``Accept: application/nostr+json``.
        SSL fallback: clearnet tries verified first, falls back to insecure if
        ``allow_insecure=True``; overlay networks always use insecure context.
    Nip66: Orchestrates six parallel health tests per relay: RTT (round-trip
        time), SSL (certificate chain), DNS (A/AAAA/CNAME), Geo (GeoIP location),
        Net (ASN info), HTTP (response headers). Each test produces a separate
        [RelayDocument][bigbrotr.models.relay_document.RelayDocument] record
        with the appropriate [DocumentType][bigbrotr.models.document.DocumentType].
    BaseData, BaseLogs, BaseNipMetadata: Shared abstract bases inherited by
        all NIP data, log, and historical-name result-container models.
    BaseNip: Abstract base class for top-level NIP models with ``relay``
        and ``generated_at`` plus semantic ``fetch()`` / ``probe()``
        entrypoints on concrete subclasses.
    BaseNipSelection: Base for selection models controlling which document or
        probe families to retrieve.
    BaseNipOptions: Base for options models controlling how NIP documents are
        retrieved (provides the common ``allow_insecure`` option).
    BaseNipDependencies: Base for dependency containers holding external objects
        (keys, database readers) required by specific NIP tests.
    NIP_REGISTRY: Static registry of built-in NIP capability bundles, including
        canonical document families, event kinds, service relevance, and
        explicit capability labels for NIP-11, NIP-66, and NIP-85.
    NipCapability: Canonical capability enum used by the static NIP registry.
    get_nip_entry: Lookup helper for one static NIP registry entry.
    nips_for_service: Static lookup from service name to relevant NIP numbers.
    nips_for_document_type: Static lookup from document type to relevant NIP numbers.
    nips_for_event_kind: Static lookup from event kind to relevant NIP numbers.
    nips_for_capability: Static lookup from capability label to relevant NIP numbers.

See Also:
    [bigbrotr.models.document.DocumentType][bigbrotr.models.document.DocumentType]:
        Enum with the canonical stored-document families exposed by the shared
        database.
    [bigbrotr.models.document.Document][bigbrotr.models.document.Document]:
        Content-addressed document model that wraps NIP results for storage.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that orchestrates NIP-11 and NIP-66 checks per relay.
"""

import importlib


__all__ = [
    "NIP_REGISTRY",
    "Nip11",
    "Nip66",
    "NipCapability",
    "NipEntry",
    "get_nip_entry",
    "nips_for_capability",
    "nips_for_document_type",
    "nips_for_event_kind",
    "nips_for_service",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "NIP_REGISTRY": ("bigbrotr.nips.registry", "NIP_REGISTRY"),
    "NipCapability": ("bigbrotr.nips.registry", "NipCapability"),
    "Nip11": ("bigbrotr.nips.nip11", "Nip11"),
    "Nip66": ("bigbrotr.nips.nip66", "Nip66"),
    "NipEntry": ("bigbrotr.nips.registry", "NipEntry"),
    "get_nip_entry": ("bigbrotr.nips.registry", "get_nip_entry"),
    "nips_for_capability": ("bigbrotr.nips.registry", "nips_for_capability"),
    "nips_for_document_type": ("bigbrotr.nips.registry", "nips_for_document_type"),
    "nips_for_event_kind": ("bigbrotr.nips.registry", "nips_for_event_kind"),
    "nips_for_service": ("bigbrotr.nips.registry", "nips_for_service"),
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
