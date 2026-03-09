"""Unit tests for bigbrotr.models.constants module."""

from enum import IntEnum, StrEnum

from bigbrotr.models.constants import EVENT_KIND_MAX, EventKind, NetworkType, ServiceName


class TestNetworkType:
    """Tests for NetworkType StrEnum."""

    def test_is_str_enum(self) -> None:
        assert isinstance(NetworkType.CLEARNET, str)
        assert isinstance(NetworkType.CLEARNET, StrEnum)

    def test_all_values(self) -> None:
        expected = {"clearnet", "tor", "i2p", "loki", "local", "unknown"}
        assert {v.value for v in NetworkType} == expected

    def test_member_count(self) -> None:
        assert len(NetworkType) == 6

    def test_string_comparison(self) -> None:
        assert NetworkType.CLEARNET == "clearnet"
        assert NetworkType.TOR == "tor"
        assert NetworkType.I2P == "i2p"
        assert NetworkType.LOKI == "loki"
        assert NetworkType.LOCAL == "local"
        assert NetworkType.UNKNOWN == "unknown"

    def test_construct_from_value(self) -> None:
        assert NetworkType("clearnet") is NetworkType.CLEARNET
        assert NetworkType("tor") is NetworkType.TOR

    def test_dict_key(self) -> None:
        d = {NetworkType.CLEARNET: 1, NetworkType.TOR: 2}
        assert d[NetworkType.CLEARNET] == 1
        assert d["clearnet"] == 1

    def test_reexported_from_models_init(self) -> None:
        from bigbrotr.models import NetworkType as ReexportedNetworkType

        assert ReexportedNetworkType is NetworkType


class TestServiceName:
    """Tests for ServiceName StrEnum."""

    def test_is_str_enum(self) -> None:
        assert isinstance(ServiceName.SEEDER, str)
        assert isinstance(ServiceName.SEEDER, StrEnum)

    def test_member_count(self) -> None:
        assert len(ServiceName) == 8

    def test_members(self) -> None:
        expected = {
            "SEEDER",
            "FINDER",
            "VALIDATOR",
            "MONITOR",
            "SYNCHRONIZER",
            "REFRESHER",
            "API",
            "DVM",
        }
        assert {m.name for m in ServiceName} == expected

    def test_values(self) -> None:
        assert ServiceName.SEEDER.value == "seeder"
        assert ServiceName.FINDER.value == "finder"
        assert ServiceName.VALIDATOR.value == "validator"
        assert ServiceName.MONITOR.value == "monitor"
        assert ServiceName.SYNCHRONIZER.value == "synchronizer"
        assert ServiceName.REFRESHER.value == "refresher"
        assert ServiceName.API.value == "api"
        assert ServiceName.DVM.value == "dvm"

    def test_string_comparison(self) -> None:
        assert ServiceName.FINDER == "finder"

    def test_dict_key(self) -> None:
        d = {ServiceName.MONITOR: "running"}
        assert d[ServiceName.MONITOR] == "running"
        assert d["monitor"] == "running"


class TestEventKind:
    """Tests for EventKind IntEnum."""

    def test_is_int_enum(self) -> None:
        assert isinstance(EventKind.CONTACTS, int)
        assert isinstance(EventKind.CONTACTS, IntEnum)

    def test_member_count(self) -> None:
        assert len(EventKind) == 7

    def test_members(self) -> None:
        assert EventKind.SET_METADATA == 0
        assert EventKind.RECOMMEND_RELAY == 2
        assert EventKind.CONTACTS == 3
        assert EventKind.RELAY_LIST == 10002
        assert EventKind.NIP66_TEST == 22456
        assert EventKind.MONITOR_ANNOUNCEMENT == 10166
        assert EventKind.RELAY_DISCOVERY == 30166

    def test_event_kind_max(self) -> None:
        assert EVENT_KIND_MAX == 65535

    def test_all_kinds_within_max(self) -> None:
        for kind in EventKind:
            assert kind <= EVENT_KIND_MAX
