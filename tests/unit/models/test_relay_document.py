"""Unit tests for the RelayDocument model."""

import json
from dataclasses import FrozenInstanceError
from time import time

import pytest

from bigbrotr.models import Relay, RelayDocument
from bigbrotr.models.document import Document, DocumentType
from bigbrotr.models.relay_document import RelayDocumentDbParams


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def relay():
    return Relay("wss://relay.example.com:8080/nostr", stored_at=1234567890)


@pytest.fixture
def document():
    return Document(type=DocumentType.NIP11_INFO, data={"name": "Test", "value": 42})


@pytest.fixture
def relay_document(relay, document):
    return RelayDocument(relay=relay, document=document, associated_at=1234567890)


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """RelayDocument construction."""

    def test_with_all_params(self, relay):
        document = Document(type=DocumentType.NIP11_INFO, data={"name": "Test"})
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        assert rm.relay is relay
        assert rm.document is document
        assert rm.document.type == DocumentType.NIP11_INFO
        assert rm.associated_at == 1234567890

    def test_associated_at_defaults_to_now(self, relay):
        before = int(time())
        document = Document(type=DocumentType.NIP11_INFO, data={"name": "Test"})
        rm = RelayDocument(relay=relay, document=document)
        after = int(time())
        assert before <= rm.associated_at <= after

    def test_associated_at_explicit(self, relay):
        document = Document(type=DocumentType.NIP66_RTT, data={"rtt": 100})
        rm = RelayDocument(relay=relay, document=document, associated_at=9999999999)
        assert rm.associated_at == 9999999999

    @pytest.mark.parametrize(
        "mtype",
        [
            DocumentType.NIP11_INFO,
            DocumentType.NIP66_RTT,
            DocumentType.NIP66_SSL,
            DocumentType.NIP66_GEO,
            DocumentType.NIP66_NET,
            DocumentType.NIP66_DNS,
            DocumentType.NIP66_HTTP,
        ],
    )
    def test_all_roles(self, relay, mtype):
        document = Document(type=mtype, data={"test": "data"})
        rm = RelayDocument(relay=relay, document=document)
        assert rm.document.type == mtype

    def test_custom_role_allowed(self, relay):
        document = Document(type="custom_role", data={"test": "data"})
        rm = RelayDocument(relay=relay, document=document)
        assert rm.document.type == "custom_role"


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_relay_mutation_blocked(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.relay = Relay("wss://other.relay", stored_at=9999999999)

    def test_document_mutation_blocked(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.document = Document(type=DocumentType.NIP11_INFO, data={"other": "data"})

    def test_associated_at_mutation_blocked(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        with pytest.raises(FrozenInstanceError):
            rm.associated_at = 9999999999

    def test_new_attribute_blocked(self, relay, document):
        rm = RelayDocument(relay=relay, document=document)
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            rm.new_attr = "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """RelayDocument.to_db_params() method."""

    def test_returns_relay_document_db_params(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        result = rm.to_db_params()
        assert isinstance(result, RelayDocumentDbParams)
        assert isinstance(result, tuple)
        assert len(result) == 7
        assert isinstance(result.document_id, bytes)
        assert len(result.document_id) == 32

    def test_structure(self, relay):
        document = Document(type=DocumentType.NIP66_RTT, data={"name": "Test", "value": 42})
        rm = RelayDocument(relay=relay, document=document, associated_at=9999999999)
        result = rm.to_db_params()
        assert result.relay_url == "wss://relay.example.com:8080/nostr"
        assert result.relay_network == "clearnet"
        assert result.relay_stored_at == 1234567890
        parsed = json.loads(result.document_data)
        assert parsed == {"name": "Test", "value": 42}
        assert result.role == "nip66_rtt"
        assert result.associated_at == 9999999999

    def test_custom_role_round_trips(self, relay):
        document = Document(type="custom_role", data={"name": "Test"})
        rm = RelayDocument(relay=relay, document=document, associated_at=9999999999)
        result = rm.to_db_params()
        assert result.role == "custom_role"

    def test_with_tor_relay(self):
        from tests.fixtures.relays import ONION_HOST

        tor_relay = Relay(f"ws://{ONION_HOST}.onion", stored_at=1234567890)
        document = Document(type=DocumentType.NIP11_INFO, data={"test": "data"})
        rm = RelayDocument(relay=tor_relay, document=document, associated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == f"ws://{ONION_HOST}.onion"
        assert result.relay_network == "tor"

    def test_with_i2p_relay(self):
        i2p_relay = Relay("ws://relay.i2p", stored_at=1234567890)
        document = Document(type=DocumentType.NIP66_GEO, data={"test": "data"})
        rm = RelayDocument(relay=i2p_relay, document=document, associated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "ws://relay.i2p"
        assert result.relay_network == "i2p"

    def test_document_id_matches_content_hash(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        result = rm.to_db_params()
        assert result.document_id == document.content_hash

    def test_caching(self, relay, document):
        rm = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        assert rm.to_db_params() is rm.to_db_params()


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self, relay, document):
        rm1 = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        rm2 = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        assert rm1 == rm2

    def test_different_type(self, relay):
        document1 = Document(type=DocumentType.NIP11_INFO, data={"test": "data"})
        document2 = Document(type=DocumentType.NIP66_RTT, data={"test": "data"})
        rm1 = RelayDocument(relay=relay, document=document1, associated_at=1234567890)
        rm2 = RelayDocument(relay=relay, document=document2, associated_at=1234567890)
        assert rm1 != rm2

    def test_different_associated_at(self, relay, document):
        rm1 = RelayDocument(relay=relay, document=document, associated_at=1234567890)
        rm2 = RelayDocument(relay=relay, document=document, associated_at=9999999999)
        assert rm1 != rm2

    def test_different_relay(self, document):
        relay1 = Relay("wss://relay1.example.com", stored_at=1234567890)
        relay2 = Relay("wss://relay2.example.com", stored_at=1234567890)
        rm1 = RelayDocument(relay=relay1, document=document, associated_at=1234567890)
        rm2 = RelayDocument(relay=relay2, document=document, associated_at=1234567890)
        assert rm1 != rm2

    def test_different_document_value(self, relay):
        document1 = Document(type=DocumentType.NIP11_INFO, data={"key": "value1"})
        document2 = Document(type=DocumentType.NIP11_INFO, data={"key": "value2"})
        rm1 = RelayDocument(relay=relay, document=document1, associated_at=1234567890)
        rm2 = RelayDocument(relay=relay, document=document2, associated_at=1234567890)
        assert rm1 != rm2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_with_empty_document(self, relay):
        empty_document = Document(type=DocumentType.NIP11_INFO, data={})
        rm = RelayDocument(relay=relay, document=empty_document, associated_at=1234567890)
        result = rm.to_db_params()
        assert result.document_data == "{}"

    def test_with_complex_document(self, relay):
        complex_document = Document(
            type=DocumentType.NIP66_NET,
            data={
                "name": "Test Relay",
                "nested": {"deep": {"value": [1, 2, 3]}},
                "tags": ["tag1", "tag2"],
            },
        )
        rm = RelayDocument(relay=relay, document=complex_document, associated_at=1234567890)
        result = rm.to_db_params()
        parsed = json.loads(result.document_data)
        assert parsed["nested"]["deep"]["value"] == [1, 2, 3]

    def test_associated_at_zero(self, relay):
        document = Document(type=DocumentType.NIP11_INFO, data={"test": "data"})
        rm = RelayDocument(relay=relay, document=document, associated_at=0)
        assert rm.associated_at == 0

    def test_with_ipv6_relay(self):
        ipv6_relay = Relay("wss://[2001:4860:4860::8888]", stored_at=1234567890)
        document = Document(type=DocumentType.NIP66_DNS, data={"dns": "data"})
        rm = RelayDocument(relay=ipv6_relay, document=document, associated_at=1234567890)
        result = rm.to_db_params()
        assert result.relay_url == "wss://[2001:4860:4860::8888]"
        assert result.relay_network == "clearnet"


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_relay_non_relay_rejected(self):
        document = Document(type=DocumentType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="relay must be a Relay"):
            RelayDocument(relay="not a relay", document=document, associated_at=123)  # type: ignore[arg-type]

    def test_document_non_document_rejected(self, relay):
        with pytest.raises(TypeError, match="document must be a Document"):
            RelayDocument(relay=relay, document="not document", associated_at=123)  # type: ignore[arg-type]

    def test_associated_at_non_int_rejected(self, relay):
        document = Document(type=DocumentType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="associated_at must be an int"):
            RelayDocument(relay=relay, document=document, associated_at="abc")  # type: ignore[arg-type]

    def test_associated_at_bool_rejected(self, relay):
        document = Document(type=DocumentType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError, match="associated_at must be an int"):
            RelayDocument(relay=relay, document=document, associated_at=True)  # type: ignore[arg-type]

    def test_associated_at_negative_rejected(self, relay):
        document = Document(type=DocumentType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(ValueError, match="associated_at must be non-negative"):
            RelayDocument(relay=relay, document=document, associated_at=-1)
