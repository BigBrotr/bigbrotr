"""Tests for models.relay_metadata module."""

import json
from time import time
from typing import get_args

import pytest

from models import Metadata, Relay, RelayMetadata
from models.relay_metadata import MetadataType


@pytest.fixture
def relay():
    """Create a test Relay."""
    return Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)


@pytest.fixture
def metadata():
    """Create a test Metadata."""
    return Metadata({"name": "Test", "value": 42})


class TestConstruction:
    """RelayMetadata construction."""

    def test_with_all_params(self, relay, metadata):
        rm = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        assert rm.relay is relay
        assert rm.metadata is metadata
        assert rm.metadata_type == "nip11"
        assert rm.generated_at == 1234567890

    def test_generated_at_defaults_to_now(self, relay, metadata):
        before = int(time())
        rm = RelayMetadata(relay, metadata, "nip11")
        after = int(time())
        assert before <= rm.generated_at <= after

    @pytest.mark.parametrize("mtype", ["nip11", "nip66_rtt", "nip66_ssl", "nip66_geo"])
    def test_metadata_types(self, relay, metadata, mtype):
        rm = RelayMetadata(relay, metadata, mtype)
        assert rm.metadata_type == mtype


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self, relay, metadata):
        rm = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        with pytest.raises(AttributeError):
            rm.metadata_type = "nip66_rtt"

    def test_new_attribute_blocked(self, relay, metadata):
        rm = RelayMetadata(relay, metadata, "nip11")
        with pytest.raises(AttributeError):
            rm.new_attr = "value"


class TestToDbParams:
    """RelayMetadata.to_db_params() method."""

    def test_returns_tuple_of_six(self, relay, metadata):
        rm = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        result = rm.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 6

    def test_structure(self, relay, metadata):
        rm = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=9999999999)
        result = rm.to_db_params()
        assert result[0] == "relay.example.com:8080/nostr"  # url
        assert result[1] == "clearnet"                       # network
        assert result[2] == 1234567890                       # relay discovered_at
        assert result[3] == 9999999999                       # generated_at
        assert result[4] == "nip66_rtt"                      # type
        parsed = json.loads(result[5])
        assert parsed == {"name": "Test", "value": 42}


class TestEquality:
    """Equality behavior."""

    def test_equal(self, relay, metadata):
        rm1 = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        assert rm1 == rm2

    def test_different_type(self, relay, metadata):
        rm1 = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip66_rtt", generated_at=1234567890)
        assert rm1 != rm2

    def test_different_generated_at(self, relay, metadata):
        rm1 = RelayMetadata(relay, metadata, "nip11", generated_at=1234567890)
        rm2 = RelayMetadata(relay, metadata, "nip11", generated_at=9999999999)
        assert rm1 != rm2


class TestMetadataTypeLiteral:
    """MetadataType Literal type."""

    def test_valid_types(self):
        valid = get_args(MetadataType)
        assert set(valid) == {"nip11", "nip66_rtt", "nip66_ssl", "nip66_geo"}
