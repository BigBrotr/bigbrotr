"""Built-in static NIP capability registry.

The registry is intentionally static and lightweight. It describes the
built-in NIP capability bundles that ship with BigBrotr today, including:

- canonical document families;
- Nostr event kinds touched by each bundle;
- the services that operationally rely on that bundle;
- the capability labels the rest of the system can reason about.

It does not provide plugin discovery or runtime loading semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.document import DocumentType

from .nip11 import Nip11, Nip11Dependencies, Nip11Options, Nip11Selection
from .nip66 import Nip66, Nip66Dependencies, Nip66Options, Nip66Selection


if TYPE_CHECKING:
    from bigbrotr.nips.base import BaseNip, BaseNipDependencies, BaseNipOptions, BaseNipSelection


class NipCapability(StrEnum):
    """Canonical capability labels used by the static NIP registry."""

    FETCH = "fetch"
    RELAY_DOCUMENT = "relay_document"
    PROBE = "probe"
    MONITOR_EVENTS = "monitor_events"
    TRUSTED_PROVIDER_DECLARATIONS = "trusted_provider_declarations"
    TRUSTED_ASSERTIONS = "trusted_assertions"
    EVENT_BUILDERS = "event_builders"
    PUBLIC_SCORES = "public_scores"


@dataclass(frozen=True, slots=True)
class NipEntry:
    """Registry entry describing one built-in NIP capability bundle."""

    slug: str
    model_cls: type[BaseNip] | None
    selection_cls: type[BaseNipSelection] | None
    options_cls: type[BaseNipOptions] | None
    dependencies_cls: type[BaseNipDependencies] | None
    document_types: tuple[DocumentType, ...]
    protocol_event_kinds: tuple[EventKind, ...]
    capabilities: tuple[NipCapability, ...]
    service_names: tuple[ServiceName, ...]

    @property
    def has_runtime_model(self) -> bool:
        """Whether the bundle exposes a concrete top-level NIP model."""
        return self.model_cls is not None

    def supports_capability(self, capability: NipCapability | str) -> bool:
        """Return whether the bundle declares the given canonical capability."""
        normalized = _normalize_capability(capability)
        return normalized is not None and normalized in self.capabilities

    def supports_service(self, service_name: ServiceName | str) -> bool:
        """Return whether the bundle is operationally relevant to one service."""
        normalized = _normalize_service_name(service_name)
        return normalized is not None and normalized in self.service_names


NIP_REGISTRY: dict[int, NipEntry] = {
    11: NipEntry(
        slug="nip11",
        model_cls=Nip11,
        selection_cls=Nip11Selection,
        options_cls=Nip11Options,
        dependencies_cls=Nip11Dependencies,
        document_types=(DocumentType.NIP11_INFO,),
        protocol_event_kinds=(),
        capabilities=(NipCapability.FETCH, NipCapability.RELAY_DOCUMENT),
        service_names=(ServiceName.MONITOR,),
    ),
    66: NipEntry(
        slug="nip66",
        model_cls=Nip66,
        selection_cls=Nip66Selection,
        options_cls=Nip66Options,
        dependencies_cls=Nip66Dependencies,
        document_types=(
            DocumentType.NIP66_RTT,
            DocumentType.NIP66_SSL,
            DocumentType.NIP66_GEO,
            DocumentType.NIP66_NET,
            DocumentType.NIP66_DNS,
            DocumentType.NIP66_HTTP,
        ),
        protocol_event_kinds=(
            EventKind.NIP66_TEST,
            EventKind.MONITOR_ANNOUNCEMENT,
            EventKind.RELAY_DISCOVERY,
        ),
        capabilities=(
            NipCapability.PROBE,
            NipCapability.RELAY_DOCUMENT,
            NipCapability.MONITOR_EVENTS,
        ),
        service_names=(ServiceName.MONITOR,),
    ),
    85: NipEntry(
        slug="nip85",
        model_cls=None,
        selection_cls=None,
        options_cls=None,
        dependencies_cls=None,
        document_types=(),
        protocol_event_kinds=(
            EventKind.NIP85_TRUSTED_PROVIDER_LIST,
            EventKind.NIP85_USER_ASSERTION,
            EventKind.NIP85_EVENT_ASSERTION,
            EventKind.NIP85_ADDRESSABLE_ASSERTION,
            EventKind.NIP85_IDENTIFIER_ASSERTION,
        ),
        capabilities=(
            NipCapability.TRUSTED_PROVIDER_DECLARATIONS,
            NipCapability.TRUSTED_ASSERTIONS,
            NipCapability.EVENT_BUILDERS,
            NipCapability.PUBLIC_SCORES,
        ),
        service_names=(ServiceName.RANKER, ServiceName.ASSERTOR),
    ),
}


def get_nip_entry(nip_number: int) -> NipEntry:
    """Return one static NIP registry entry by number."""
    return NIP_REGISTRY[nip_number]


def nips_for_service(service_name: ServiceName | str) -> tuple[int, ...]:
    """Return NIP numbers operationally relevant to one service."""
    normalized = _normalize_service_name(service_name)
    if normalized is None:
        return ()
    return tuple(
        nip_number
        for nip_number, entry in NIP_REGISTRY.items()
        if normalized in entry.service_names
    )


def nips_for_document_type(document_type: DocumentType | str) -> tuple[int, ...]:
    """Return NIP numbers that own or describe one canonical document type."""
    normalized = _normalize_document_type(document_type)
    if normalized is None:
        return ()
    return tuple(
        nip_number
        for nip_number, entry in NIP_REGISTRY.items()
        if normalized in entry.document_types
    )


def nips_for_event_kind(event_kind: EventKind | int) -> tuple[int, ...]:
    """Return NIP numbers associated with one Nostr event kind."""
    normalized = _normalize_event_kind(event_kind)
    if normalized is None:
        return ()
    return tuple(
        nip_number
        for nip_number, entry in NIP_REGISTRY.items()
        if any(int(kind) == normalized for kind in entry.protocol_event_kinds)
    )


def nips_for_capability(capability: NipCapability | str) -> tuple[int, ...]:
    """Return NIP numbers that expose one canonical capability label."""
    normalized = _normalize_capability(capability)
    if normalized is None:
        return ()
    return tuple(
        nip_number for nip_number, entry in NIP_REGISTRY.items() if normalized in entry.capabilities
    )


def _normalize_service_name(service_name: ServiceName | str) -> ServiceName | None:
    if isinstance(service_name, ServiceName):
        return service_name
    try:
        return ServiceName(service_name)
    except ValueError:
        return None


def _normalize_document_type(document_type: DocumentType | str) -> DocumentType | None:
    if isinstance(document_type, DocumentType):
        return document_type
    try:
        return DocumentType(document_type)
    except ValueError:
        return None


def _normalize_event_kind(event_kind: EventKind | int) -> int | None:
    if isinstance(event_kind, EventKind):
        return int(event_kind)
    if isinstance(event_kind, int):
        return event_kind
    return None


def _normalize_capability(capability: NipCapability | str) -> NipCapability | None:
    if isinstance(capability, NipCapability):
        return capability
    try:
        return NipCapability(capability)
    except ValueError:
        return None
