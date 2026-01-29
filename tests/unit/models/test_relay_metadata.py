"""
Unit tests for models.relay_metadata module.

Tests:
- RelayMetadata construction from Relay and Metadata
- MetadataType StrEnum (nip11_fetch, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http)
- RelayMetadataDbParams NamedTuple structure (6 fields)
- to_db_params() serialization for bulk insert
- from_db_params() deserialization
- generated_at timestamp handling (default vs explicit)
- Immutability enforcement (frozen dataclass)
- Equality behavior
"""

import json
from dataclasses import FrozenInstanceError
from time import time

import pytest

from models import Metadata, Relay, RelayMetadata
from models.relay import NetworkType
from models.relay_metadata import MetadataType, RelayMetadataDbParams


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def relay():
    """Create a test Relay."""
    return Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)


@pytest.fixture
def metadata():
    """Create a test Metadata."""
    return Metadata({"name": "Test", "value": 42})


@pytest.fixture
def relay_metadata(relay, metadata):
    """Create a RelayMetadata with explicit generated_at."""
    return RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)


# =============================================================================
# MetadataType Enum Tests
# =============================================================================


class TestMetadataTypeEnum:
    """MetadataType StrEnum."""

    def test_all_valid_types(self):
        """All expected metadata types exist."""
        valid = {member.value for member in MetadataType}
        assert valid == {
            "nip11_fetch",
            "nip66_rtt",
            "nip66_ssl",
            "nip66_geo",
            "nip66_net",
            "nip66_dns",
            "nip66_http",
        }

    def test_str_compatibility(self):
        """MetadataType values are string compatible."""
        assert MetadataType.NIP11_FETCH == "nip11_fetch"
        assert MetadataType.NIP66_RTT == "nip66_rtt"
        assert MetadataType.NIP66_SSL == "nip66_ssl"
        assert MetadataType.NIP66_GEO == "nip66_geo"
        assert MetadataType.NIP66_NET == "nip66_net"
        assert MetadataType.NIP66_DNS == "nip66_dns"
        assert MetadataType.NIP66_HTTP == "nip66_http"

    def test_str_conversion(self):
        """str() converts to string value."""
        assert str(MetadataType.NIP11_FETCH) == "nip11_fetch"
        assert str(MetadataType.NIP66_RTT) == "nip66_rtt"

    def test_can_use_as_dict_key(self):
        """MetadataType can be used as dict key."""
        d = {MetadataType.NIP11_FETCH: 1, MetadataType.NIP66_RTT: 2}
        assert d[MetadataType.NIP11_FETCH] == 1
        assert d["nip11_fetch"] == 1


# =============================================================================
# RelayMetadataDbParams Tests
# =============================================================================


class TestRelayMetadataDbParams:
    """Test RelayMetadataDbParams NamedTuple."""

    def test_is_named_tuple(self):
        """RelayMetadataDbParams is a NamedTuple with 7 fields."""
        params = RelayMetadataDbParams(
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            metadata_id=b"\x00" * 32,
            metadata_json='{"key": "value"}',
            metadata_type="nip11_fetch",
            generated_at=1234567891,
        )
        assert isinstance(params, tuple)
        assert len(params) == 7

    def test_field_access_by_name(self):
        """Fields are accessible by name."""
        test_hash = b"\x01\x02\x03" + b"\x00" * 29
        params = RelayMetadataDbParams(
            relay_url="wss://relay.test:8080",
            relay_network="tor",
            relay_discovered_at=1000000000,
            metadata_id=test_hash,
            metadata_json='{"name": "test"}',
            metadata_type="nip66_rtt",
            generated_at=2000000000,
        )
        assert params.relay_url == "wss://relay.test:8080"
        assert params.relay_network == "tor"
        assert params.relay_discovered_at == 1000000000
        assert params.metadata_id == test_hash
        assert params.metadata_json == '{"name": "test"}'
        assert params.metadata_type == "nip66_rtt"
        assert params.generated_at == 2000000000

    def test_field_access_by_index(self):
        """Fields are accessible by index."""
        test_hash = b"\x00" * 32
        params = RelayMetadataDbParams(
            relay_url="ws://abc.onion",
            relay_network="tor",
            relay_discovered_at=1111111111,
            metadata_id=test_hash,
            metadata_json="{}",
            metadata_type="nip66_ssl",
            generated_at=2222222222,
        )
        assert params[0] == "ws://abc.onion"  # relay_url
        assert params[1] == "tor"  # relay_network
        assert params[2] == 1111111111  # relay_discovered_at
        assert params[3] == test_hash  # metadata_id
        assert params[4] == "{}"  # metadata_json
        assert params[5] == "nip66_ssl"  # metadata_type
        assert params[6] == 2222222222  # generated_at

    def test_immutability(self):
        """RelayMetadataDbParams is immutable (NamedTuple)."""
        params = RelayMetadataDbParams(
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            metadata_id=b"\x00" * 32,
            metadata_json="{}",
            metadata_type="nip11_fetch",
            generated_at=1234567891,
        )
        with pytest.raises(AttributeError):
            params.generated_at = 9999999999


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """RelayMetadata construction."""

    def test_with_all_params(self, relay, metadata):
        """Constructs with all parameters explicitly set."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        assert rm.relay is relay
        assert rm.metadata is metadata
        assert rm.metadata_type == "nip11_fetch"
        assert rm.generated_at == 1234567890

    def test_generated_at_defaults_to_now(self, relay, metadata):
        """generated_at defaults to current time if not provided."""
        before = int(time())
        rm = RelayMetadata(relay, metadata, "nip11_fetch")
        after = int(time())
        assert before <= rm.generated_at <= after

    def test_generated_at_explicit(self, relay, metadata):
        """Explicit generated_at is preserved."""
        rm = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=9999999999)
        assert rm.generated_at == 9999999999

    @pytest.mark.parametrize(
        "mtype",
        [
            "nip11_fetch",
            "nip66_rtt",
            "nip66_ssl",
            "nip66_geo",
            "nip66_net",
            "nip66_dns",
            "nip66_http",
        ],
    )
    def test_all_metadata_types(self, relay, metadata, mtype):
        """All metadata types can be used."""
        rm = RelayMetadata(relay, metadata, mtype)
        assert rm.metadata_type == mtype

    def test_with_metadata_type_enum(self, relay, metadata):
        """Can use MetadataType enum value."""
        rm = RelayMetadata(relay, metadata, MetadataType.NIP11_FETCH)
        assert rm.metadata_type == "nip11_fetch"


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_relay_mutation_blocked(self, relay, metadata):
        """Cannot modify relay attribute."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        new_relay = Relay("wss://other.relay", discovered_at=9999999999)
        with pytest.raises(FrozenInstanceError):
            rm.relay = new_relay

    def test_metadata_mutation_blocked(self, relay, metadata):
        """Cannot modify metadata attribute."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        new_metadata = Metadata({"other": "data"})
        with pytest.raises(FrozenInstanceError):
            rm.metadata = new_metadata

    def test_metadata_type_mutation_blocked(self, relay, metadata):
        """Cannot modify metadata_type attribute."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.metadata_type = "nip66_rtt"

    def test_generated_at_mutation_blocked(self, relay, metadata):
        """Cannot modify generated_at attribute."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.generated_at = 9999999999

    def test_new_attribute_blocked(self, relay, metadata):
        """Cannot add new attributes."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch")
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            rm.new_attr = "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """RelayMetadata.to_db_params() method."""

    def test_returns_relay_metadata_db_params(self, relay, metadata):
        """Returns RelayMetadataDbParams NamedTuple with 7 elements."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        result = rm.to_db_params()
        assert isinstance(result, RelayMetadataDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 7
        assert isinstance(result.metadata_id, bytes)
        assert len(result.metadata_id) == 32  # SHA-256 hash

    def test_structure(self, relay, metadata):
        """Verifies correct field values."""
        rm = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=9999999999)
        result = rm.to_db_params()
        # Relay fields
        assert result.relay_url == "wss://relay.example.com:8080/nostr"
        assert result.relay_network == "clearnet"
        assert result.relay_discovered_at == 1234567890
        # Metadata field (JSON)
        parsed = json.loads(result.metadata_json)
        assert parsed == {"name": "Test", "value": 42}
        # Type and timestamp
        assert result.metadata_type == "nip66_rtt"
        assert result.generated_at == 9999999999

    def test_with_tor_relay(self, metadata):
        """Works with Tor relay."""
        tor_relay = Relay("wss://abc123.onion", discovered_at=1234567890)
        rm = RelayMetadata(tor_relay, metadata, "nip11_fetch", generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "ws://abc123.onion"
        assert result.relay_network == "tor"

    def test_with_i2p_relay(self, metadata):
        """Works with I2P relay."""
        i2p_relay = Relay("wss://relay.i2p", discovered_at=1234567890)
        rm = RelayMetadata(i2p_relay, metadata, "nip66_geo", generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "ws://relay.i2p"
        assert result.relay_network == "i2p"


# =============================================================================
# from_db_params Tests
# =============================================================================


class TestFromDbParams:
    """RelayMetadata.from_db_params() deserialization."""

    def test_simple(self):
        """Reconstructs RelayMetadata from db params."""
        rm = RelayMetadata.from_db_params(
            relay_url="wss://relay.example.com",
            relay_network="clearnet",
            relay_discovered_at=1234567890,
            metadata_json='{"name": "Test"}',
            metadata_type="nip11_fetch",
            generated_at=9999999999,
        )
        assert rm.relay.url == "wss://relay.example.com"
        assert rm.relay.network == NetworkType.CLEARNET
        assert rm.relay.discovered_at == 1234567890
        assert rm.metadata.metadata == {"name": "Test"}
        assert rm.metadata_type == "nip11_fetch"
        assert rm.generated_at == 9999999999

    def test_with_tor_relay(self):
        """Reconstructs with Tor relay."""
        rm = RelayMetadata.from_db_params(
            relay_url="ws://abc123.onion",
            relay_network="tor",
            relay_discovered_at=1234567890,
            metadata_json="{}",
            metadata_type="nip66_rtt",
            generated_at=1234567891,
        )
        assert rm.relay.network == NetworkType.TOR
        assert rm.relay.scheme == "ws"

    def test_roundtrip(self, relay, metadata):
        """to_db_params -> from_db_params preserves data."""
        original = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=1234567890)
        params = original.to_db_params()
        # from_db_params doesn't take metadata_id (it's computed from JSON)
        reconstructed = RelayMetadata.from_db_params(
            relay_url=params.relay_url,
            relay_network=params.relay_network,
            relay_discovered_at=params.relay_discovered_at,
            metadata_json=params.metadata_json,
            metadata_type=params.metadata_type,
            generated_at=params.generated_at,
        )
        assert reconstructed.relay.url == original.relay.url
        assert reconstructed.relay.network == original.relay.network
        assert reconstructed.relay.discovered_at == original.relay.discovered_at
        assert reconstructed.metadata.metadata == original.metadata.metadata
        assert reconstructed.metadata_type == original.metadata_type
        assert reconstructed.generated_at == original.generated_at

    def test_roundtrip_all_metadata_types(self, relay, metadata):
        """Roundtrip works for all metadata types."""
        for mtype in MetadataType:
            original = RelayMetadata(relay, metadata, mtype, generated_at=1234567890)
            params = original.to_db_params()
            # from_db_params doesn't take metadata_id (it's computed from JSON)
            reconstructed = RelayMetadata.from_db_params(
                relay_url=params.relay_url,
                relay_network=params.relay_network,
                relay_discovered_at=params.relay_discovered_at,
                metadata_json=params.metadata_json,
                metadata_type=params.metadata_type,
                generated_at=params.generated_at,
            )
            assert reconstructed.metadata_type == mtype


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self, relay, metadata):
        """RelayMetadata with same attributes are equal."""
        rm1 = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        assert rm1 == rm2

    def test_different_type(self, relay, metadata):
        """RelayMetadata with different type are not equal."""
        rm1 = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=1234567890)
        assert rm1 != rm2

    def test_different_generated_at(self, relay, metadata):
        """RelayMetadata with different generated_at are not equal."""
        rm1 = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=9999999999)
        assert rm1 != rm2

    def test_different_relay(self, metadata):
        """RelayMetadata with different relay are not equal."""
        relay1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        rm1 = RelayMetadata(relay1, metadata, "nip11_fetch", generated_at=1234567890)
        rm2 = RelayMetadata(relay2, metadata, "nip11_fetch", generated_at=1234567890)
        assert rm1 != rm2

    def test_different_metadata(self, relay):
        """RelayMetadata with different metadata are not equal."""
        metadata1 = Metadata({"key": "value1"})
        metadata2 = Metadata({"key": "value2"})
        rm1 = RelayMetadata(relay, metadata1, "nip11_fetch", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata2, "nip11_fetch", generated_at=1234567890)
        assert rm1 != rm2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_with_empty_metadata(self, relay):
        """Works with empty metadata."""
        empty_metadata = Metadata({})
        rm = RelayMetadata(relay, empty_metadata, "nip11_fetch", generated_at=1234567890)
        result = rm.to_db_params()
        assert result.metadata_json == "{}"

    def test_with_complex_metadata(self, relay):
        """Works with complex nested metadata."""
        complex_metadata = Metadata(
            {
                "name": "Test Relay",
                "nested": {"deep": {"value": [1, 2, 3]}},
                "tags": ["tag1", "tag2"],
            }
        )
        rm = RelayMetadata(relay, complex_metadata, "nip66_net", generated_at=1234567890)
        result = rm.to_db_params()
        parsed = json.loads(result.metadata_json)
        assert parsed["nested"]["deep"]["value"] == [1, 2, 3]

    def test_generated_at_zero(self, relay, metadata):
        """generated_at can be zero (epoch)."""
        rm = RelayMetadata(relay, metadata, "nip11_fetch", generated_at=0)
        assert rm.generated_at == 0

    def test_with_ipv6_relay(self, metadata):
        """Works with IPv6 relay."""
        ipv6_relay = Relay("wss://[2001:4860:4860::8888]", discovered_at=1234567890)
        rm = RelayMetadata(ipv6_relay, metadata, "nip66_dns", generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "wss://[2001:4860:4860::8888]"
        assert result.relay_network == "clearnet"
