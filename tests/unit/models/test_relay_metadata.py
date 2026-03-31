"""Unit tests for the RelayMetadata model."""

import json
from dataclasses import FrozenInstanceError
from time import time

import pytest

from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay_metadata import RelayMetadataDbParams


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def relay():
    return Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)


@pytest.fixture
def metadata():
    return Metadata(type=MetadataType.NIP11_INFO, data={"name": "Test", "value": 42})


@pytest.fixture
def relay_metadata(relay, metadata):
    return RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """RelayMetadata construction."""

    def test_with_all_params(self, relay):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Test"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        assert rm.relay is relay
        assert rm.metadata is metadata
        assert rm.metadata.type == MetadataType.NIP11_INFO
        assert rm.generated_at == 1234567890

    def test_generated_at_defaults_to_now(self, relay):
        before = int(time())
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Test"})
        rm = RelayMetadata(relay=relay, metadata=metadata)
        after = int(time())
        assert before <= rm.generated_at <= after

    def test_generated_at_explicit(self, relay):
        metadata = Metadata(type=MetadataType.NIP66_RTT, data={"rtt": 100})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=9999999999)
        assert rm.generated_at == 9999999999

    @pytest.mark.parametrize(
        "mtype",
        [
            MetadataType.NIP11_INFO,
            MetadataType.NIP66_RTT,
            MetadataType.NIP66_SSL,
            MetadataType.NIP66_GEO,
            MetadataType.NIP66_NET,
            MetadataType.NIP66_DNS,
            MetadataType.NIP66_HTTP,
        ],
    )
    def test_all_metadata_types(self, relay, mtype):
        metadata = Metadata(type=mtype, data={"test": "data"})
        rm = RelayMetadata(relay=relay, metadata=metadata)
        assert rm.metadata.type == mtype


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_relay_mutation_blocked(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.relay = Relay("wss://other.relay", discovered_at=9999999999)

    def test_metadata_mutation_blocked(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.metadata = Metadata(type=MetadataType.NIP11_INFO, data={"other": "data"})

    def test_generated_at_mutation_blocked(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.generated_at = 9999999999

    def test_new_attribute_blocked(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata)
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            rm.new_attr = "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """RelayMetadata.to_db_params() method."""

    def test_returns_relay_metadata_db_params(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert isinstance(result, RelayMetadataDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 7
        assert isinstance(result.metadata_id, bytes)
        assert len(result.metadata_id) == 32

    def test_structure(self, relay):
        metadata = Metadata(type=MetadataType.NIP66_RTT, data={"name": "Test", "value": 42})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=9999999999)
        result = rm.to_db_params()
        assert result.relay_url == "wss://relay.example.com:8080/nostr"
        assert result.relay_network == "clearnet"
        assert result.relay_discovered_at == 1234567890
        parsed = json.loads(result.metadata_data)
        assert parsed == {"name": "Test", "value": 42}
        assert result.metadata_type == "nip66_rtt"
        assert result.generated_at == 9999999999

    def test_with_tor_relay(self):
        from tests.fixtures.relays import ONION_HOST

        tor_relay = Relay(f"ws://{ONION_HOST}.onion", discovered_at=1234567890)
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"test": "data"})
        rm = RelayMetadata(relay=tor_relay, metadata=metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == f"ws://{ONION_HOST}.onion"
        assert result.relay_network == "tor"

    def test_with_i2p_relay(self):
        i2p_relay = Relay("ws://relay.i2p", discovered_at=1234567890)
        metadata = Metadata(type=MetadataType.NIP66_GEO, data={"test": "data"})
        rm = RelayMetadata(relay=i2p_relay, metadata=metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "ws://relay.i2p"
        assert result.relay_network == "i2p"

    def test_metadata_id_matches_content_hash(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert result.metadata_id == metadata.content_hash

    def test_caching(self, relay, metadata):
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        assert rm.to_db_params() is rm.to_db_params()


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self, relay, metadata):
        rm1 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        rm2 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        assert rm1 == rm2

    def test_different_type(self, relay):
        metadata1 = Metadata(type=MetadataType.NIP11_INFO, data={"test": "data"})
        metadata2 = Metadata(type=MetadataType.NIP66_RTT, data={"test": "data"})
        rm1 = RelayMetadata(relay=relay, metadata=metadata1, generated_at=1234567890)
        rm2 = RelayMetadata(relay=relay, metadata=metadata2, generated_at=1234567890)
        assert rm1 != rm2

    def test_different_generated_at(self, relay, metadata):
        rm1 = RelayMetadata(relay=relay, metadata=metadata, generated_at=1234567890)
        rm2 = RelayMetadata(relay=relay, metadata=metadata, generated_at=9999999999)
        assert rm1 != rm2

    def test_different_relay(self, metadata):
        relay1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        rm1 = RelayMetadata(relay=relay1, metadata=metadata, generated_at=1234567890)
        rm2 = RelayMetadata(relay=relay2, metadata=metadata, generated_at=1234567890)
        assert rm1 != rm2

    def test_different_metadata_value(self, relay):
        metadata1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value1"})
        metadata2 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value2"})
        rm1 = RelayMetadata(relay=relay, metadata=metadata1, generated_at=1234567890)
        rm2 = RelayMetadata(relay=relay, metadata=metadata2, generated_at=1234567890)
        assert rm1 != rm2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_with_empty_metadata(self, relay):
        empty_metadata = Metadata(type=MetadataType.NIP11_INFO, data={})
        rm = RelayMetadata(relay=relay, metadata=empty_metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert result.metadata_data == "{}"

    def test_with_complex_metadata(self, relay):
        complex_metadata = Metadata(
            type=MetadataType.NIP66_NET,
            data={
                "name": "Test Relay",
                "nested": {"deep": {"value": [1, 2, 3]}},
                "tags": ["tag1", "tag2"],
            },
        )
        rm = RelayMetadata(relay=relay, metadata=complex_metadata, generated_at=1234567890)
        result = rm.to_db_params()
        parsed = json.loads(result.metadata_data)
        assert parsed["nested"]["deep"]["value"] == [1, 2, 3]

    def test_generated_at_zero(self, relay):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"test": "data"})
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=0)
        assert rm.generated_at == 0

    def test_with_ipv6_relay(self):
        ipv6_relay = Relay("wss://[2001:4860:4860::8888]", discovered_at=1234567890)
        metadata = Metadata(type=MetadataType.NIP66_DNS, data={"dns": "data"})
        rm = RelayMetadata(relay=ipv6_relay, metadata=metadata, generated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "wss://[2001:4860:4860::8888]"
        assert result.relay_network == "clearnet"


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_relay_non_relay_rejected(self):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="relay must be a Relay"):
            RelayMetadata(relay="not a relay", metadata=metadata, generated_at=123)  # type: ignore[arg-type]

    def test_metadata_non_metadata_rejected(self, relay):
        with pytest.raises(TypeError, match="metadata must be a Metadata"):
            RelayMetadata(relay=relay, metadata="not metadata", generated_at=123)  # type: ignore[arg-type]

    def test_generated_at_non_int_rejected(self, relay):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="generated_at must be an int"):
            RelayMetadata(relay=relay, metadata=metadata, generated_at="abc")  # type: ignore[arg-type]

    def test_generated_at_bool_rejected(self, relay):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="generated_at must be an int"):
            RelayMetadata(relay=relay, metadata=metadata, generated_at=True)  # type: ignore[arg-type]

    def test_generated_at_negative_rejected(self, relay):
        metadata = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(ValueError, match="generated_at must be non-negative"):
            RelayMetadata(relay=relay, metadata=metadata, generated_at=-1)
