"""Built-in NIP registry for capability wiring and future protocol extension.

The registry is intentionally static and lightweight. It describes the
built-in NIP capability bundles that ship with BigBrotr today without
introducing plugin discovery or runtime loading semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from bigbrotr.models.constants import EventKind
from bigbrotr.models.metadata import MetadataType

from .nip11 import Nip11, Nip11Dependencies, Nip11Options, Nip11Selection
from .nip66 import Nip66, Nip66Dependencies, Nip66Options, Nip66Selection


if TYPE_CHECKING:
    from bigbrotr.nips.base import BaseNip, BaseNipDependencies, BaseNipOptions, BaseNipSelection


class NipEntry(NamedTuple):
    """Registry entry describing one built-in NIP capability bundle."""

    slug: str
    model_cls: type[BaseNip] | None
    selection_cls: type[BaseNipSelection] | None
    options_cls: type[BaseNipOptions] | None
    dependencies_cls: type[BaseNipDependencies] | None
    metadata_types: tuple[str, ...]
    protocol_event_kinds: tuple[int, ...]
    capabilities: tuple[str, ...]


NIP_REGISTRY: dict[int, NipEntry] = {
    11: NipEntry(
        slug="nip11",
        model_cls=Nip11,
        selection_cls=Nip11Selection,
        options_cls=Nip11Options,
        dependencies_cls=Nip11Dependencies,
        metadata_types=(MetadataType.NIP11_INFO,),
        protocol_event_kinds=(),
        capabilities=("fetch", "relay_metadata"),
    ),
    66: NipEntry(
        slug="nip66",
        model_cls=Nip66,
        selection_cls=Nip66Selection,
        options_cls=Nip66Options,
        dependencies_cls=Nip66Dependencies,
        metadata_types=(
            MetadataType.NIP66_RTT,
            MetadataType.NIP66_SSL,
            MetadataType.NIP66_GEO,
            MetadataType.NIP66_NET,
            MetadataType.NIP66_DNS,
            MetadataType.NIP66_HTTP,
        ),
        protocol_event_kinds=(
            int(EventKind.NIP66_TEST),
            int(EventKind.MONITOR_ANNOUNCEMENT),
            int(EventKind.RELAY_DISCOVERY),
        ),
        capabilities=("probe", "relay_metadata", "monitor_events"),
    ),
    85: NipEntry(
        slug="nip85",
        model_cls=None,
        selection_cls=None,
        options_cls=None,
        dependencies_cls=None,
        metadata_types=(),
        protocol_event_kinds=(
            int(EventKind.NIP85_TRUSTED_PROVIDER_LIST),
            int(EventKind.NIP85_USER_ASSERTION),
            int(EventKind.NIP85_EVENT_ASSERTION),
            int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
            int(EventKind.NIP85_IDENTIFIER_ASSERTION),
        ),
        capabilities=("trusted_provider_declarations", "trusted_assertions", "event_builders"),
    ),
}
