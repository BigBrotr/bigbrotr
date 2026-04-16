"""Unit tests for the Metadata model and MetadataType enum."""

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from bigbrotr.models.metadata import Metadata, MetadataDbParams, MetadataType


# =============================================================================
# MetadataType Enum Tests
# =============================================================================


class TestMetadataTypeEnum:
    """MetadataType StrEnum."""

    def test_all_valid_types(self):
        valid = {member.value for member in MetadataType}
        assert valid == {
            "nip11_info",
            "nip66_rtt",
            "nip66_ssl",
            "nip66_geo",
            "nip66_net",
            "nip66_dns",
            "nip66_http",
        }

    def test_member_count(self):
        assert len(MetadataType) == 7

    def test_str_compatibility(self):
        assert MetadataType.NIP11_INFO == "nip11_info"
        assert MetadataType.NIP66_RTT == "nip66_rtt"
        assert MetadataType.NIP66_SSL == "nip66_ssl"
        assert MetadataType.NIP66_GEO == "nip66_geo"
        assert MetadataType.NIP66_NET == "nip66_net"
        assert MetadataType.NIP66_DNS == "nip66_dns"
        assert MetadataType.NIP66_HTTP == "nip66_http"

    def test_str_conversion(self):
        assert str(MetadataType.NIP11_INFO) == "nip11_info"
        assert str(MetadataType.NIP66_RTT) == "nip66_rtt"

    def test_can_use_as_dict_key(self):
        d = {MetadataType.NIP11_INFO: 1, MetadataType.NIP66_RTT: 2}
        assert d[MetadataType.NIP11_INFO] == 1
        assert d["nip11_info"] == 1

    def test_construct_from_value(self):
        assert MetadataType("nip11_info") is MetadataType.NIP11_INFO


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """Metadata construction and initialization."""

    def test_with_dict(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test", "value": 123})
        assert m.data == {"name": "test", "value": 123}
        assert m.type == "nip11_info"

    def test_with_none_rejected(self):
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data=None)  # type: ignore[arg-type]

    def test_without_args(self):
        m = Metadata(type=MetadataType.NIP11_INFO)
        assert m.data == {}

    def test_with_empty_dict(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        assert m.data == {}

    def test_custom_type_allowed(self):
        m = Metadata(type="custom_metadata_type", data={"name": "test"})
        assert m.type == "custom_metadata_type"

    def test_with_nested(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"outer": {"inner": "value"}})
        assert m.data["outer"]["inner"] == "value"

    def test_with_list_values(self):
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"items": [1, 2, 3], "names": ["a", "b", "c"]}
        )
        assert m.data["items"] == (1, 2, 3)
        assert m.data["names"] == ("a", "b", "c")

    def test_with_mixed_types(self):
        data = {
            "string": "text",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, "two", 3.0],
            "nested": {"key": "value"},
        }
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        assert m.data["string"] == "text"
        assert m.data["number"] == 42
        assert m.data["float"] == 3.14
        assert m.data["bool"] is True
        assert m.data["null"] is None


# =============================================================================
# Content Hash Property Tests
# =============================================================================


class TestContentHash:
    """content_hash property returns SHA-256 of canonical JSON."""

    def test_returns_32_bytes(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert isinstance(m.content_hash, bytes)
        assert len(m.content_hash) == 32

    def test_deterministic(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert m1.content_hash == m2.content_hash

    def test_different_data_different_hash(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test1"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test2"})
        assert m1.content_hash != m2.content_hash

    def test_type_not_included_in_hash(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        m2 = Metadata(type=MetadataType.NIP66_RTT, data={"name": "test"})
        assert m1.content_hash == m2.content_hash

    def test_matches_manual_sha256(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        expected = hashlib.sha256(m.canonical_json.encode("utf-8")).digest()
        assert m.content_hash == expected


# =============================================================================
# Canonical JSON Property Tests
# =============================================================================


class TestCanonicalJson:
    """canonical_json property returns deterministic JSON."""

    def test_returns_string(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert isinstance(m.canonical_json, str)

    def test_sorted_keys(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"z": 1, "a": 2})
        assert m.canonical_json == '{"a":2,"z":1}'

    def test_compact_separators(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert " " not in m.canonical_json

    def test_unicode_preserved(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"})
        assert "Relay" in m.canonical_json

    def test_empty_dict(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        assert m.canonical_json == "{}"

    def test_deterministic_across_key_order(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        assert m1.canonical_json == m2.canonical_json


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(FrozenInstanceError):
            m.data = {"new": "data"}  # type: ignore[misc]

    def test_new_attribute_blocked(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            m.new_attr = "value"


# =============================================================================
# Sanitization Tests
# =============================================================================


class TestSanitize:
    """Strict validation plus normalization in __post_init__."""

    def test_non_string_keys_rejected(self):
        with pytest.raises(TypeError, match="data keys must be str, got int"):
            Metadata(type=MetadataType.NIP11_INFO, data={1: "value", "key": "value"})

    def test_non_serializable_value_rejected(self):
        class Custom:
            pass

        with pytest.raises(TypeError, match="data contains unsupported type Custom"):
            Metadata(type=MetadataType.NIP11_INFO, data={"valid": "ok", "invalid": Custom()})

    def test_non_finite_float_rejected(self):
        with pytest.raises(ValueError, match="data contains a non-finite float"):
            Metadata(type=MetadataType.NIP11_INFO, data={"value": float("inf")})

    def test_null_bytes_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            Metadata(type=MetadataType.NIP11_INFO, data={"text": "hello\x00world"})

    def test_deeply_nested_normalization(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"l1": {"l2": {"l3": {"l4": "value"}}}})
        assert m.data["l1"]["l2"]["l3"]["l4"] == "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Metadata.to_db_params() for PostgreSQL JSONB."""

    def test_returns_metadata_db_params(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        result = m.to_db_params()
        assert isinstance(result, MetadataDbParams)
        assert len(result) == 3
        assert isinstance(result.id, bytes)
        assert len(result.id) == 32
        assert result.type == "nip11_info"

    def test_valid_json(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test", "value": 123})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed == {"name": "test", "value": 123}

    def test_empty_dict(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        assert m.to_db_params().data == "{}"

    def test_unicode(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"})
        assert "Relay" in m.to_db_params().data

    def test_nested(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"a": {"b": {"c": [1, 2, 3]}}})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed["a"]["b"]["c"] == [1, 2, 3]

    def test_caching(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert m.to_db_params() is m.to_db_params()

    def test_id_matches_content_hash(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert m.to_db_params().id == m.content_hash

    def test_data_matches_canonical_json(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        assert m.to_db_params().data == m.canonical_json


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        assert m1 == m2

    def test_different_value(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value1"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value2"})
        assert m1 != m2

    def test_different_type(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP66_RTT, data={"key": "value"})
        assert m1 != m2

    def test_not_hashable(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(TypeError):
            hash(m)


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_unicode_values(self):
        data = {"name": "World", "japanese": "Nostr"}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_large_data(self):
        data = {"items": list(range(10000))}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == {"items": tuple(range(10000))}

    def test_special_json_characters(self):
        data = {"text": 'Hello "World"\nNew line\ttab'}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_null_values_preserved(self):
        data = {"value": None, "nested": {"inner": None}, "real": "data"}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_boolean_values(self):
        data = {"true": True, "false": False}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data
        assert reconstructed.data["true"] is True
        assert reconstructed.data["false"] is False

    def test_numeric_precision(self):
        data = {"int": 9007199254740992, "float": 3.14159}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data["int"] == 9007199254740992
        assert abs(reconstructed.data["float"] - 3.14159) < 1e-10

    def test_deeply_nested(self):
        data = {"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_list_as_data_rejected(self):
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data=[1, 2, 3])

    def test_string_as_data_rejected(self):
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data="not a dict")

    def test_empty_string_values(self):
        data = {"empty": "", "nested": {"also_empty": ""}}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data["empty"] == ""
        assert reconstructed.data["nested"]["also_empty"] == ""


# =============================================================================
# Normalization Tests (for content-addressed deduplication)
# =============================================================================


class TestNormalization:
    """Tests for JSON normalization ensuring deterministic hashing."""

    def test_empty_dicts_preserved(self):
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"name": "Relay", "limitation": {}, "fees": {}}
        )
        assert m.data == {"fees": {}, "limitation": {}, "name": "Relay"}

    def test_empty_lists_preserved(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay", "tags": [], "nips": []})
        assert m.data == {"name": "Relay", "nips": (), "tags": ()}

    def test_nested_empty_preserved_recursively(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"level1": {"level2": {"level3": {}}}})
        assert m.data == {"level1": {"level2": {"level3": {}}}}

    def test_non_empty_preserved(self):
        m = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Relay", "limitation": {"max": 1000}, "fees": {}},
        )
        assert m.data == {"fees": {}, "limitation": {"max": 1000}, "name": "Relay"}

    def test_keys_sorted(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"z": 1, "a": 2, "m": 3})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 2, "m": 3, "z": 1})
        assert m1.to_db_params().data == m2.to_db_params().data

    def test_hash_distinguishes_empty_containers(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay", "limitation": {}})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"})
        assert m1.content_hash != m2.content_hash

    def test_hash_consistency_key_order(self):
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        assert m1.content_hash == m2.content_hash

    def test_empty_in_lists_preserved(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"items": [1, [], 2, {}, 3]})
        assert m.data == {"items": (1, (), 2, {}, 3)}

    def test_none_in_lists_preserved(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"items": [1, None, 2, None, 3]})
        assert m.data == {"items": (1, None, 2, None, 3)}

    def test_falsy_values_preserved(self):
        m = Metadata(type=MetadataType.NIP11_INFO, data={"enabled": False, "count": 0, "name": ""})
        assert m.data == {"count": 0, "enabled": False, "name": ""}

    def test_list_can_carry_only_empty_values(self):
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"items": [None, {}, [], None], "real": "data"}
        )
        assert m.data == {"items": (None, {}, (), None), "real": "data"}


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_type_empty_rejected(self):
        with pytest.raises(ValueError, match="type must not be empty"):
            Metadata(type="", data={"key": "value"})

    def test_type_int_rejected(self):
        with pytest.raises(TypeError, match="type must be a str"):
            Metadata(type=42, data={"key": "value"})  # type: ignore[arg-type]
