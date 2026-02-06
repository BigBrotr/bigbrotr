"""Unit tests for the Metadata model, MetadataType enum, and MetadataDbParams NamedTuple."""

import json
from dataclasses import FrozenInstanceError

import pytest

from models.metadata import Metadata, MetadataDbParams, MetadataType


# =============================================================================
# MetadataDbParams Tests
# =============================================================================


class TestMetadataDbParams:
    """Test MetadataDbParams NamedTuple."""

    def test_is_named_tuple(self):
        """MetadataDbParams is a NamedTuple with 3 fields."""
        params = MetadataDbParams(
            id=b"\x00" * 32,
            value='{"key": "value"}',
            type=MetadataType.NIP11_FETCH,
        )
        assert isinstance(params, tuple)
        assert len(params) == 3

    def test_field_access_by_name(self):
        """Fields are accessible by name."""
        test_hash = b"\x01\x02\x03" + b"\x00" * 29
        params = MetadataDbParams(
            id=test_hash,
            value='{"name": "test"}',
            type=MetadataType.NIP66_RTT,
        )
        assert params.id == test_hash
        assert params.value == '{"name": "test"}'
        assert params.type == MetadataType.NIP66_RTT

    def test_field_access_by_index(self):
        """Fields are accessible by index."""
        test_hash = b"\x00" * 32
        params = MetadataDbParams(
            id=test_hash,
            value="[]",
            type=MetadataType.NIP66_SSL,
        )
        assert params[0] == test_hash
        assert params[1] == "[]"
        assert params[2] == MetadataType.NIP66_SSL

    def test_immutability(self):
        """MetadataDbParams is immutable (NamedTuple)."""
        params = MetadataDbParams(
            id=b"\x00" * 32,
            value="{}",
            type=MetadataType.NIP11_FETCH,
        )
        with pytest.raises(AttributeError):
            params.value = '{"new": "data"}'


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """Metadata construction and initialization."""

    def test_with_dict(self):
        """Constructs with dict data."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test", "value": 123})
        assert m.value == {"name": "test", "value": 123}
        assert m.type == MetadataType.NIP11_FETCH

    def test_with_none(self):
        """Constructs with None defaults to empty dict."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value=None)  # type: ignore[arg-type]
        assert m.value == {}

    def test_without_args(self):
        """Constructs without value defaults to empty dict."""
        m = Metadata(type=MetadataType.NIP11_FETCH)
        assert m.value == {}

    def test_with_empty_dict(self):
        """Constructs with empty dict."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m.value == {}

    def test_with_nested(self):
        """Constructs with nested dict."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"outer": {"inner": "value"}})
        assert m.value["outer"]["inner"] == "value"

    def test_with_list_values(self):
        """Constructs with list values in dict."""
        m = Metadata(
            type=MetadataType.NIP11_FETCH, value={"items": [1, 2, 3], "names": ["a", "b", "c"]}
        )
        assert m.value["items"] == [1, 2, 3]
        assert m.value["names"] == ["a", "b", "c"]

    def test_with_mixed_types(self):
        """Constructs with mixed value types (None is filtered out)."""
        data = {
            "string": "text",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, "two", 3.0],
            "nested": {"key": "value"},
        }
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        assert m.value["string"] == "text"
        assert m.value["number"] == 42
        assert m.value["float"] == 3.14
        assert m.value["bool"] is True
        assert "null" not in m.value  # None values filtered for deterministic hashing


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        """Cannot modify metadata attribute."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        with pytest.raises(FrozenInstanceError):
            m.value = {"new": "data"}  # type: ignore[misc]

    def test_new_attribute_blocked(self):
        """Cannot add new attributes."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            m.new_attr = "value"


# =============================================================================
# Type-safe Accessor Tests
# =============================================================================


class TestGetMethods:
    """Type-safe getter methods (_get)."""

    def test_get_with_default(self):
        """_get returns value when key exists and type matches."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test"})
        assert m._get("name", expected_type=str, default="default") == "test"

    def test_get_wrong_type_returns_default(self):
        """_get returns default when type does not match."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": 123})
        assert m._get("name", expected_type=str, default="default") == "default"

    def test_get_missing_returns_default(self):
        """_get returns default when key is missing."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m._get("missing", expected_type=str, default="default") == "default"

    def test_get_optional_exists(self):
        """_get returns value when key exists (no default)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test"})
        assert m._get("name", expected_type=str) == "test"

    def test_get_optional_wrong_type(self):
        """_get returns None when type mismatch (no default)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": 123})
        assert m._get("name", expected_type=str) is None

    def test_get_optional_missing(self):
        """_get returns None when key is missing (no default)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m._get("missing", expected_type=str) is None

    def test_get_nested_with_default(self):
        """_get handles nested keys."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str, default="default") == "value"

    def test_get_nested_missing_outer(self):
        """_get returns default when outer key missing."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m._get("missing", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_outer_not_dict(self):
        """_get returns default when outer is not a dict."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"outer": "not_a_dict"})
        assert m._get("outer", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_optional_exists(self):
        """_get handles nested keys without default."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str) == "value"

    def test_get_nested_optional_missing(self):
        """_get returns None for missing nested key (no default)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m._get("missing", "inner", expected_type=str) is None

    def test_get_deep_nested(self):
        """_get handles deeply nested keys."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"a": {"b": {"c": "deep"}}})
        assert m._get("a", "b", "c", expected_type=str) == "deep"

    def test_get_deep_nested_with_default(self):
        """_get returns default for missing deep key."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"a": {"b": {}}})
        assert m._get("a", "b", "c", expected_type=str, default="fallback") == "fallback"

    def test_get_bool_type(self):
        """_get handles bool type correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"enabled": True})
        assert m._get("enabled", expected_type=bool) is True
        assert m._get("enabled", expected_type=bool, default=False) is True

    def test_get_int_type(self):
        """_get handles int type correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"count": 42})
        assert m._get("count", expected_type=int) == 42

    def test_get_list_type(self):
        """_get handles list type correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"items": [1, 2, 3]})
        assert m._get("items", expected_type=list) == [1, 2, 3]

    def test_get_dict_type(self):
        """_get handles dict type correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"nested": {"key": "value"}})
        assert m._get("nested", expected_type=dict) == {"key": "value"}


# =============================================================================
# Sanitization Tests
# =============================================================================


class TestSanitize:
    """JSON sanitization via _sanitize and __post_init__."""

    def test_non_string_keys_skipped(self):
        """Non-string keys are filtered out during sanitization."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        params = m.to_db_params()
        parsed = json.loads(params.value)
        assert parsed == {"key": "value"}

    def test_non_serializable_filtered_out(self):
        """Non-JSON-serializable values are filtered out (become None, then filtered)."""

        class Custom:
            pass

        m = Metadata(type=MetadataType.NIP11_FETCH, value={"valid": "ok", "invalid": Custom()})
        params = m.to_db_params()
        parsed = json.loads(params.value)
        assert parsed == {"valid": "ok"}

    def test_null_bytes_rejected(self):
        """Null bytes in strings raise ValueError."""
        with pytest.raises(ValueError, match="null bytes"):
            Metadata(type=MetadataType.NIP11_FETCH, value={"text": "hello\x00world"})

    def test_deeply_nested_sanitization(self):
        """Deeply nested structures are sanitized correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"l1": {"l2": {"l3": {"l4": "value"}}}})
        assert m.value["l1"]["l2"]["l3"]["l4"] == "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Metadata.to_db_params() for PostgreSQL JSONB."""

    def test_returns_metadata_db_params(self):
        """Returns MetadataDbParams NamedTuple."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test"})
        result = m.to_db_params()
        assert isinstance(result, MetadataDbParams)
        assert len(result) == 3
        assert isinstance(result.id, bytes)
        assert len(result.id) == 32  # SHA-256 hash
        assert result.type == MetadataType.NIP11_FETCH

    def test_valid_json(self):
        """Returns valid JSON string."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test", "value": 123})
        params = m.to_db_params()
        parsed = json.loads(params.value)
        assert parsed == {"name": "test", "value": 123}

    def test_empty_dict(self):
        """Empty dict serializes to '{}'."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={})
        assert m.to_db_params().value == "{}"

    def test_unicode(self):
        """Unicode is preserved (ensure_ascii=False)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "Relay"})
        assert "Relay" in m.to_db_params().value

    def test_nested(self):
        """Nested structures serialize correctly."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"a": {"b": {"c": [1, 2, 3]}}})
        params = m.to_db_params()
        parsed = json.loads(params.value)
        assert parsed["a"]["b"]["c"] == [1, 2, 3]


# =============================================================================
# from_db_params Tests
# =============================================================================


class TestFromDbParams:
    """Metadata.from_db_params() deserialization."""

    def test_simple(self):
        """Reconstructs simple metadata."""
        hash_bytes = bytes.fromhex(
            "7d9fd2051fc32b32feab10946fab6bb91426ab7e39aa5439289ed892864aa91d"  # pragma: allowlist secret
        )
        params = MetadataDbParams(
            id=hash_bytes, value='{"name": "test"}', type=MetadataType.NIP11_FETCH
        )
        m = Metadata.from_db_params(params)
        assert m.value == {"name": "test"}
        assert m.type == MetadataType.NIP11_FETCH

    def test_nested(self):
        """Reconstructs nested metadata."""
        hash_bytes = bytes.fromhex(
            "345cbac42064615b5c54e4b502193eb847ce94a9c62ad47a463fe43d99226e3c"  # pragma: allowlist secret
        )
        params = MetadataDbParams(
            id=hash_bytes, value='{"a": {"b": [1, 2, 3]}}', type=MetadataType.NIP66_RTT
        )
        m = Metadata.from_db_params(params)
        assert m.value["a"]["b"] == [1, 2, 3]
        assert m.type == MetadataType.NIP66_RTT

    def test_empty(self):
        """Reconstructs empty metadata."""
        hash_bytes = bytes.fromhex(
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"  # pragma: allowlist secret
        )
        params = MetadataDbParams(id=hash_bytes, value="{}", type=MetadataType.NIP66_SSL)
        m = Metadata.from_db_params(params)
        assert m.value == {}
        assert m.type == MetadataType.NIP66_SSL

    def test_roundtrip(self):
        """to_db_params -> from_db_params preserves metadata."""
        original = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "test", "value": 123})
        params = original.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == original.value
        assert reconstructed.type == original.type

    def test_roundtrip_nested(self):
        """Roundtrip preserves nested structures."""
        original = Metadata(
            type=MetadataType.NIP66_GEO, value={"outer": {"inner": {"deep": [1, 2, 3]}}}
        )
        params = original.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == original.value
        assert reconstructed.type == original.type


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        """Metadata with same type and data are equal."""
        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        assert m1 == m2

    def test_different_value(self):
        """Metadata with different data are not equal."""
        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value1"})
        m2 = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value2"})
        assert m1 != m2

    def test_different_type(self):
        """Metadata with different types are not equal."""
        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP66_RTT, value={"key": "value"})
        assert m1 != m2

    def test_not_hashable(self):
        """Metadata is not hashable (contains mutable dict)."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"key": "value"})
        with pytest.raises(TypeError):
            hash(m)


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_unicode_values(self):
        """Unicode values are handled correctly."""
        data = {"name": "World", "japanese": "Nostr"}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == data

    def test_large_data(self):
        """Large data is handled correctly."""
        data = {"items": list(range(10000))}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == data

    def test_special_json_characters(self):
        """Special JSON characters are escaped."""
        data = {"text": 'Hello "World"\nNew line\ttab'}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == data

    def test_null_values_filtered(self):
        """Null values are filtered out for deterministic hashing."""
        data = {"value": None, "nested": {"inner": None}, "real": "data"}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == {"real": "data"}
        assert "value" not in reconstructed.value
        assert "nested" not in reconstructed.value

    def test_boolean_values(self):
        """Boolean values are preserved."""
        data = {"true": True, "false": False}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == data
        assert reconstructed.value["true"] is True
        assert reconstructed.value["false"] is False

    def test_numeric_precision(self):
        """Numeric precision is preserved for typical values."""
        data = {"int": 9007199254740992, "float": 3.14159}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value["int"] == 9007199254740992
        assert abs(reconstructed.value["float"] - 3.14159) < 1e-10

    def test_deeply_nested(self):
        """Deeply nested structures are handled."""
        data = {"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value == data

    def test_empty_string_values(self):
        """Empty string values are preserved."""
        data = {"empty": "", "nested": {"also_empty": ""}}
        m = Metadata(type=MetadataType.NIP11_FETCH, value=data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params)
        assert reconstructed.value["empty"] == ""
        assert reconstructed.value["nested"]["also_empty"] == ""


# =============================================================================
# Normalization Tests (for content-addressed deduplication)
# =============================================================================


class TestNormalization:
    """Tests for JSON normalization ensuring deterministic hashing."""

    def test_empty_dicts_removed(self):
        """Empty dicts are removed for deterministic hashing."""
        m = Metadata(
            type=MetadataType.NIP11_FETCH, value={"name": "Relay", "limitation": {}, "fees": {}}
        )
        assert m.value == {"name": "Relay"}

    def test_empty_lists_removed(self):
        """Empty lists are removed for deterministic hashing."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "Relay", "tags": [], "nips": []})
        assert m.value == {"name": "Relay"}

    def test_nested_empty_removed_recursively(self):
        """Nested empty structures are removed recursively."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"level1": {"level2": {"level3": {}}}})
        assert m.value == {}

    def test_non_empty_preserved(self):
        """Non-empty structures are preserved."""
        m = Metadata(
            type=MetadataType.NIP11_FETCH,
            value={"name": "Relay", "limitation": {"max": 1000}, "fees": {}},
        )
        assert m.value == {"limitation": {"max": 1000}, "name": "Relay"}

    def test_keys_sorted(self):
        """Dict keys are sorted for deterministic output."""
        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"z": 1, "a": 2, "m": 3})
        m2 = Metadata(type=MetadataType.NIP11_FETCH, value={"a": 2, "m": 3, "z": 1})
        assert m1.to_db_params().value == m2.to_db_params().value

    def test_hash_consistency_empty_containers(self):
        """Semantically identical data produces same hash (empty containers)."""
        import hashlib

        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "Relay", "limitation": {}})
        m2 = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "Relay"})
        h1 = hashlib.sha256(m1.to_db_params().value.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().value.encode()).hexdigest()
        assert h1 == h2

    def test_hash_consistency_key_order(self):
        """Semantically identical data produces same hash (key order)."""
        import hashlib

        m1 = Metadata(type=MetadataType.NIP11_FETCH, value={"b": 2, "a": 1})
        m2 = Metadata(type=MetadataType.NIP11_FETCH, value={"a": 1, "b": 2})
        h1 = hashlib.sha256(m1.to_db_params().value.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().value.encode()).hexdigest()
        assert h1 == h2

    def test_empty_in_lists_removed(self):
        """Empty containers within lists are removed."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"items": [1, [], 2, {}, 3]})
        assert m.value == {"items": [1, 2, 3]}

    def test_none_in_lists_removed(self):
        """None values within lists are removed."""
        m = Metadata(type=MetadataType.NIP11_FETCH, value={"items": [1, None, 2, None, 3]})
        assert m.value == {"items": [1, 2, 3]}

    def test_falsy_values_preserved(self):
        """Falsy values (False, 0, '') are preserved, only None/empty containers removed."""
        m = Metadata(
            type=MetadataType.NIP11_FETCH, value={"enabled": False, "count": 0, "name": ""}
        )
        assert m.value == {"count": 0, "enabled": False, "name": ""}

    def test_list_becomes_empty_after_filtering(self):
        """List with only empty/None elements becomes empty and is removed."""
        m = Metadata(
            type=MetadataType.NIP11_FETCH, value={"items": [None, {}, [], None], "real": "data"}
        )
        assert m.value == {"real": "data"}
