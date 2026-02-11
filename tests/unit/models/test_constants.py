"""Unit tests for models.constants module."""

from enum import IntEnum, StrEnum

from bigbrotr.models.constants import EVENT_KIND_MAX, EventKind, NetworkType, ServiceName


class TestNetworkType:
    """Tests for NetworkType StrEnum."""

    def test_is_str_enum(self) -> None:
        """NetworkType values are strings."""
        assert isinstance(NetworkType.CLEARNET, str)
        assert NetworkType.CLEARNET == "clearnet"

    def test_all_values(self) -> None:
        """All expected network types are defined."""
        expected = {"clearnet", "tor", "i2p", "loki", "local", "unknown"}
        assert {v.value for v in NetworkType} == expected

    def test_string_comparison(self) -> None:
        """StrEnum values can be compared with plain strings."""
        assert NetworkType.TOR == "tor"
        assert NetworkType.I2P == "i2p"
        assert NetworkType.LOKI == "loki"
        assert NetworkType.LOCAL == "local"
        assert NetworkType.UNKNOWN == "unknown"

    def test_construct_from_value(self) -> None:
        """NetworkType can be constructed from a string value."""
        assert NetworkType("clearnet") is NetworkType.CLEARNET
        assert NetworkType("tor") is NetworkType.TOR

    def test_reexported_from_models_init(self) -> None:
        """NetworkType is re-exported from the models package."""
        from bigbrotr.models import NetworkType as ReexportedNetworkType

        assert ReexportedNetworkType is NetworkType


class TestServiceName:
    """Tests for ServiceName StrEnum."""

    def test_members(self) -> None:
        """All expected service names are defined."""
        expected = {"SEEDER", "FINDER", "VALIDATOR", "MONITOR", "SYNCHRONIZER"}
        assert {m.name for m in ServiceName} == expected

    def test_values(self) -> None:
        """String values match the lowercase service names."""
        assert ServiceName.SEEDER.value == "seeder"
        assert ServiceName.FINDER.value == "finder"
        assert ServiceName.VALIDATOR.value == "validator"
        assert ServiceName.MONITOR.value == "monitor"
        assert ServiceName.SYNCHRONIZER.value == "synchronizer"

    def test_is_str_enum(self) -> None:
        """ServiceName members are both str and StrEnum instances."""
        assert isinstance(ServiceName.SEEDER, str)
        assert isinstance(ServiceName.SEEDER, StrEnum)

    def test_string_comparison(self) -> None:
        """StrEnum values can be compared with plain strings."""
        assert ServiceName.FINDER == "finder"

    def test_dict_key(self) -> None:
        """ServiceName members work as dictionary keys."""
        d = {ServiceName.MONITOR: "running"}
        assert d[ServiceName.MONITOR] == "running"
        assert d["monitor"] == "running"

    def test_member_count(self) -> None:
        """ServiceName has exactly 5 members."""
        assert len(ServiceName) == 5


class TestEventKind:
    """Tests for EventKind IntEnum."""

    def test_members(self) -> None:
        """All expected event kinds are defined with correct values."""
        assert EventKind.RECOMMEND_RELAY == 2
        assert EventKind.CONTACTS == 3
        assert EventKind.RELAY_LIST == 10002
        assert EventKind.NIP66_TEST == 22456
        assert EventKind.MONITOR_ANNOUNCEMENT == 10166
        assert EventKind.RELAY_DISCOVERY == 30166

    def test_is_int_enum(self) -> None:
        """EventKind members are both int and IntEnum instances."""
        assert isinstance(EventKind.CONTACTS, int)
        assert isinstance(EventKind.CONTACTS, IntEnum)

    def test_event_kind_max(self) -> None:
        """EVENT_KIND_MAX is the maximum valid event kind value."""
        assert EVENT_KIND_MAX == 65535

    def test_member_count(self) -> None:
        """EventKind has exactly 6 members."""
        assert len(EventKind) == 6
