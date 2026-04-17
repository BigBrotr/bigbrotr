from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.document import DocumentType
from bigbrotr.nips import (
    NIP_REGISTRY,
    NipCapability,
    NipEntry,
    get_nip_entry,
    nips_for_capability,
    nips_for_document_type,
    nips_for_event_kind,
    nips_for_service,
)
from bigbrotr.nips.nip11 import Nip11, Nip11Dependencies, Nip11Options, Nip11Selection
from bigbrotr.nips.nip66 import Nip66, Nip66Dependencies, Nip66Options, Nip66Selection


class TestNipRegistry:
    def test_supported_built_in_nips_registered(self) -> None:
        assert set(NIP_REGISTRY) == {11, 66, 85}

    def test_registry_entries_are_nip_entry(self) -> None:
        for entry in NIP_REGISTRY.values():
            assert isinstance(entry, NipEntry)

    def test_nip11_entry_exposes_top_level_types(self) -> None:
        entry = NIP_REGISTRY[11]

        assert entry.slug == "nip11"
        assert entry.model_cls is Nip11
        assert entry.selection_cls is Nip11Selection
        assert entry.options_cls is Nip11Options
        assert entry.dependencies_cls is Nip11Dependencies
        assert entry.document_types == (DocumentType.NIP11_INFO,)
        assert entry.protocol_event_kinds == ()
        assert entry.capabilities == (NipCapability.FETCH, NipCapability.RELAY_DOCUMENT)
        assert entry.service_names == (ServiceName.MONITOR,)
        assert entry.has_runtime_model is True
        assert entry.supports_capability("fetch")
        assert entry.supports_service(ServiceName.MONITOR)

    def test_nip66_entry_tracks_metadata_and_protocol_kinds(self) -> None:
        entry = NIP_REGISTRY[66]

        assert entry.slug == "nip66"
        assert entry.model_cls is Nip66
        assert entry.selection_cls is Nip66Selection
        assert entry.options_cls is Nip66Options
        assert entry.dependencies_cls is Nip66Dependencies
        assert entry.document_types == (
            DocumentType.NIP66_RTT,
            DocumentType.NIP66_SSL,
            DocumentType.NIP66_GEO,
            DocumentType.NIP66_NET,
            DocumentType.NIP66_DNS,
            DocumentType.NIP66_HTTP,
        )
        assert entry.protocol_event_kinds == (
            EventKind.NIP66_TEST,
            EventKind.MONITOR_ANNOUNCEMENT,
            EventKind.RELAY_DISCOVERY,
        )
        assert entry.capabilities == (
            NipCapability.PROBE,
            NipCapability.RELAY_DOCUMENT,
            NipCapability.MONITOR_EVENTS,
        )
        assert entry.service_names == (ServiceName.MONITOR,)
        assert entry.has_runtime_model is True

    def test_nip85_entry_is_capability_only(self) -> None:
        entry = NIP_REGISTRY[85]

        assert entry.slug == "nip85"
        assert entry.model_cls is None
        assert entry.selection_cls is None
        assert entry.options_cls is None
        assert entry.dependencies_cls is None
        assert entry.document_types == ()
        assert entry.protocol_event_kinds == (
            EventKind.NIP85_TRUSTED_PROVIDER_LIST,
            EventKind.NIP85_USER_ASSERTION,
            EventKind.NIP85_EVENT_ASSERTION,
            EventKind.NIP85_ADDRESSABLE_ASSERTION,
            EventKind.NIP85_IDENTIFIER_ASSERTION,
        )
        assert entry.capabilities == (
            NipCapability.TRUSTED_PROVIDER_DECLARATIONS,
            NipCapability.TRUSTED_ASSERTIONS,
            NipCapability.EVENT_BUILDERS,
            NipCapability.PUBLIC_SCORES,
        )
        assert entry.service_names == (ServiceName.RANKER, ServiceName.ASSERTOR)
        assert entry.has_runtime_model is False

    def test_protocol_event_kinds_are_event_kind_enums(self) -> None:
        for entry in NIP_REGISTRY.values():
            assert all(isinstance(kind, EventKind) for kind in entry.protocol_event_kinds)

    def test_lookup_helpers_follow_static_registry_contract(self) -> None:
        assert get_nip_entry(11) is NIP_REGISTRY[11]
        assert nips_for_service(ServiceName.MONITOR) == (11, 66)
        assert nips_for_service("assertor") == (85,)
        assert nips_for_document_type(DocumentType.NIP66_HTTP) == (66,)
        assert nips_for_document_type("nip11_info") == (11,)
        assert nips_for_event_kind(EventKind.MONITOR_ANNOUNCEMENT) == (66,)
        assert nips_for_event_kind(int(EventKind.NIP85_IDENTIFIER_ASSERTION)) == (85,)
        assert nips_for_capability(NipCapability.RELAY_DOCUMENT) == (11, 66)
        assert nips_for_capability("public_scores") == (85,)

    def test_lookup_helpers_return_empty_for_unknown_static_keys(self) -> None:
        assert nips_for_service("nope") == ()
        assert nips_for_document_type("nope") == ()
        assert nips_for_event_kind(99999) == ()
        assert nips_for_capability("nope") == ()
