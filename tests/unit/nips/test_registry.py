from bigbrotr.models.constants import EventKind
from bigbrotr.models.metadata import MetadataType
from bigbrotr.nips import NIP_REGISTRY, NipEntry
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
        assert entry.metadata_types == (MetadataType.NIP11_INFO,)
        assert entry.protocol_event_kinds == ()
        assert entry.capabilities == ("fetch", "relay_metadata")

    def test_nip66_entry_tracks_metadata_and_protocol_kinds(self) -> None:
        entry = NIP_REGISTRY[66]

        assert entry.slug == "nip66"
        assert entry.model_cls is Nip66
        assert entry.selection_cls is Nip66Selection
        assert entry.options_cls is Nip66Options
        assert entry.dependencies_cls is Nip66Dependencies
        assert entry.metadata_types == (
            MetadataType.NIP66_RTT,
            MetadataType.NIP66_SSL,
            MetadataType.NIP66_GEO,
            MetadataType.NIP66_NET,
            MetadataType.NIP66_DNS,
            MetadataType.NIP66_HTTP,
        )
        assert entry.protocol_event_kinds == (
            int(EventKind.NIP66_TEST),
            int(EventKind.MONITOR_ANNOUNCEMENT),
            int(EventKind.RELAY_DISCOVERY),
        )
        assert entry.capabilities == ("probe", "relay_metadata", "monitor_events")

    def test_nip85_entry_is_capability_only(self) -> None:
        entry = NIP_REGISTRY[85]

        assert entry.slug == "nip85"
        assert entry.model_cls is None
        assert entry.selection_cls is None
        assert entry.options_cls is None
        assert entry.dependencies_cls is None
        assert entry.metadata_types == ()
        assert entry.protocol_event_kinds == (
            int(EventKind.NIP85_TRUSTED_PROVIDER_LIST),
            int(EventKind.NIP85_USER_ASSERTION),
            int(EventKind.NIP85_EVENT_ASSERTION),
            int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
            int(EventKind.NIP85_IDENTIFIER_ASSERTION),
        )
        assert entry.capabilities == (
            "trusted_provider_declarations",
            "trusted_assertions",
            "event_builders",
        )

    def test_protocol_event_kinds_are_plain_ints(self) -> None:
        for entry in NIP_REGISTRY.values():
            assert all(isinstance(kind, int) for kind in entry.protocol_event_kinds)
