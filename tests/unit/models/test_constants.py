"""Unit tests for models.constants module."""

from bigbrotr.models.constants import NetworkType


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
