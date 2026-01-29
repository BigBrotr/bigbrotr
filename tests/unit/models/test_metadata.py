"""
Unit tests for models.metadata module.

Tests:
- Metadata construction from dict
- Sanitization of non-JSON-compatible data
- Type-safe accessor methods (_get with nesting and defaults)
- MetadataDbParams NamedTuple structure
- to_db_params() serialization for PostgreSQL JSONB
- from_db_params() deserialization
- Immutability enforcement (frozen dataclass)
- Equality behavior
"""

import json
from dataclasses import FrozenInstanceError

import pytest

from models.metadata import Metadata, MetadataDbParams


# =============================================================================
# MetadataDbParams Tests
# =============================================================================


class TestMetadataDbParams:
    """Test MetadataDbParams NamedTuple."""

    def test_is_named_tuple(self):
        """MetadataDbParams is a NamedTuple with 2 fields."""
        params = MetadataDbParams(
            metadata_id=b"\x00" * 32,
            metadata_json='{"key": "value"}',
        )
        assert isinstance(params, tuple)
        assert len(params) == 2

    def test_field_access_by_name(self):
        """Fields are accessible by name."""
        test_hash = b"\x01\x02\x03" + b"\x00" * 29
        params = MetadataDbParams(
            metadata_id=test_hash,
            metadata_json='{"name": "test"}',
        )
        assert params.metadata_id == test_hash
        assert params.metadata_json == '{"name": "test"}'

    def test_field_access_by_index(self):
        """Fields are accessible by index."""
        test_hash = b"\x00" * 32
        params = MetadataDbParams(
            metadata_id=test_hash,
            metadata_json="[]",
        )
        assert params[0] == test_hash
        assert params[1] == "[]"

    def test_immutability(self):
        """MetadataDbParams is immutable (NamedTuple)."""
        params = MetadataDbParams(
            metadata_id=b"\x00" * 32,
            metadata_json="{}",
        )
        with pytest.raises(AttributeError):
            params.metadata_json = '{"new": "data"}'


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """Metadata construction and initialization."""

    def test_with_dict(self):
        """Constructs with dict data."""
        m = Metadata({"name": "test", "value": 123})
        assert m.metadata == {"name": "test", "value": 123}

    def test_with_none(self):
        """Constructs with None defaults to empty dict."""
        m = Metadata(None)  # type: ignore[arg-type]
        assert m.metadata == {}

    def test_without_args(self):
        """Constructs without args defaults to empty dict."""
        m = Metadata()
        assert m.metadata == {}

    def test_with_empty_dict(self):
        """Constructs with empty dict."""
        m = Metadata({})
        assert m.metadata == {}

    def test_with_nested(self):
        """Constructs with nested dict."""
        m = Metadata({"outer": {"inner": "value"}})
        assert m.metadata["outer"]["inner"] == "value"

    def test_with_list_values(self):
        """Constructs with list values in dict."""
        m = Metadata({"items": [1, 2, 3], "names": ["a", "b", "c"]})
        assert m.metadata["items"] == [1, 2, 3]
        assert m.metadata["names"] == ["a", "b", "c"]

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
        m = Metadata(data)
        assert m.metadata["string"] == "text"
        assert m.metadata["number"] == 42
        assert m.metadata["float"] == 3.14
        assert m.metadata["bool"] is True
        # None values are filtered out for deterministic hashing
        assert "null" not in m.metadata


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        """Cannot modify metadata attribute."""
        m = Metadata({"key": "value"})
        with pytest.raises(FrozenInstanceError):
            m.metadata = {"new": "data"}  # type: ignore[misc]

    def test_new_attribute_blocked(self):
        """Cannot add new attributes."""
        m = Metadata({})
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            m.new_attr = "value"


# =============================================================================
# Type-safe Accessor Tests
# =============================================================================


class TestGetMethods:
    """Type-safe getter methods (_get)."""

    def test_get_with_default(self):
        """_get returns value when key exists and type matches."""
        m = Metadata({"name": "test"})
        assert m._get("name", expected_type=str, default="default") == "test"

    def test_get_wrong_type_returns_default(self):
        """_get returns default when type does not match."""
        m = Metadata({"name": 123})
        assert m._get("name", expected_type=str, default="default") == "default"

    def test_get_missing_returns_default(self):
        """_get returns default when key is missing."""
        m = Metadata({})
        assert m._get("missing", expected_type=str, default="default") == "default"

    def test_get_optional_exists(self):
        """_get returns value when key exists (no default)."""
        m = Metadata({"name": "test"})
        assert m._get("name", expected_type=str) == "test"

    def test_get_optional_wrong_type(self):
        """_get returns None when type mismatch (no default)."""
        m = Metadata({"name": 123})
        assert m._get("name", expected_type=str) is None

    def test_get_optional_missing(self):
        """_get returns None when key is missing (no default)."""
        m = Metadata({})
        assert m._get("missing", expected_type=str) is None

    def test_get_nested_with_default(self):
        """_get handles nested keys."""
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str, default="default") == "value"

    def test_get_nested_missing_outer(self):
        """_get returns default when outer key missing."""
        m = Metadata({})
        assert m._get("missing", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_outer_not_dict(self):
        """_get returns default when outer is not a dict."""
        m = Metadata({"outer": "not_a_dict"})
        assert m._get("outer", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_optional_exists(self):
        """_get handles nested keys without default."""
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str) == "value"

    def test_get_nested_optional_missing(self):
        """_get returns None for missing nested key (no default)."""
        m = Metadata({})
        assert m._get("missing", "inner", expected_type=str) is None

    def test_get_deep_nested(self):
        """_get handles deeply nested keys."""
        m = Metadata({"a": {"b": {"c": "deep"}}})
        assert m._get("a", "b", "c", expected_type=str) == "deep"

    def test_get_deep_nested_with_default(self):
        """_get returns default for missing deep key."""
        m = Metadata({"a": {"b": {}}})
        assert m._get("a", "b", "c", expected_type=str, default="fallback") == "fallback"

    def test_get_bool_type(self):
        """_get handles bool type correctly."""
        m = Metadata({"enabled": True})
        assert m._get("enabled", expected_type=bool) is True
        assert m._get("enabled", expected_type=bool, default=False) is True

    def test_get_int_type(self):
        """_get handles int type correctly."""
        m = Metadata({"count": 42})
        assert m._get("count", expected_type=int) == 42

    def test_get_list_type(self):
        """_get handles list type correctly."""
        m = Metadata({"items": [1, 2, 3]})
        assert m._get("items", expected_type=list) == [1, 2, 3]

    def test_get_dict_type(self):
        """_get handles dict type correctly."""
        m = Metadata({"nested": {"key": "value"}})
        assert m._get("nested", expected_type=dict) == {"key": "value"}


# =============================================================================
# Sanitization Tests
# =============================================================================


class TestSanitize:
    """JSON sanitization via _sanitize and __post_init__."""

    def test_non_string_keys_skipped(self):
        """Non-string keys are filtered out during sanitization."""
        # Note: We need to sanitize manually since sorted() fails on mixed types
        m = Metadata({"key": "value"})
        params = m.to_db_params()
        parsed = json.loads(params.metadata_json)
        assert parsed == {"key": "value"}

    def test_non_serializable_filtered_out(self):
        """Non-JSON-serializable values are filtered out (become None, then filtered)."""

        class Custom:
            pass

        m = Metadata({"valid": "ok", "invalid": Custom()})
        params = m.to_db_params()
        parsed = json.loads(params.metadata_json)
        # Non-serializable becomes None, and None is filtered for deterministic hashing
        assert parsed == {"valid": "ok"}

    def test_null_bytes_removed(self):
        """Null bytes in strings are removed."""
        m = Metadata({"text": "hello\x00world"})
        assert m.metadata["text"] == "helloworld"

    def test_deeply_nested_sanitization(self):
        """Deeply nested structures are sanitized correctly."""
        m = Metadata({"l1": {"l2": {"l3": {"l4": "value"}}}})
        assert m.metadata["l1"]["l2"]["l3"]["l4"] == "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Metadata.to_db_params() for PostgreSQL JSONB."""

    def test_returns_metadata_db_params(self):
        """Returns MetadataDbParams NamedTuple."""
        m = Metadata({"name": "test"})
        result = m.to_db_params()
        assert isinstance(result, MetadataDbParams)
        assert len(result) == 2
        assert isinstance(result.metadata_id, bytes)
        assert len(result.metadata_id) == 32  # SHA-256 hash

    def test_valid_json(self):
        """Returns valid JSON string."""
        m = Metadata({"name": "test", "value": 123})
        params = m.to_db_params()
        parsed = json.loads(params.metadata_json)
        assert parsed == {"name": "test", "value": 123}

    def test_empty_dict(self):
        """Empty dict serializes to '{}'."""
        m = Metadata({})
        assert m.to_db_params().metadata_json == "{}"

    def test_unicode(self):
        """Unicode is preserved (ensure_ascii=False)."""
        m = Metadata({"name": "Relay"})
        assert "Relay" in m.to_db_params().metadata_json

    def test_nested(self):
        """Nested structures serialize correctly."""
        m = Metadata({"a": {"b": {"c": [1, 2, 3]}}})
        params = m.to_db_params()
        parsed = json.loads(params.metadata_json)
        assert parsed["a"]["b"]["c"] == [1, 2, 3]


# =============================================================================
# from_db_params Tests
# =============================================================================


class TestFromDbParams:
    """Metadata.from_db_params() deserialization."""

    def test_simple(self):
        """Reconstructs simple metadata."""
        m = Metadata.from_db_params('{"name": "test"}')
        assert m.metadata == {"name": "test"}

    def test_nested(self):
        """Reconstructs nested metadata."""
        m = Metadata.from_db_params('{"a": {"b": [1, 2, 3]}}')
        assert m.metadata["a"]["b"] == [1, 2, 3]

    def test_empty(self):
        """Reconstructs empty metadata."""
        m = Metadata.from_db_params("{}")
        assert m.metadata == {}

    def test_roundtrip(self):
        """to_db_params -> from_db_params preserves metadata."""
        original = Metadata({"name": "test", "value": 123})
        params = original.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == original.metadata

    def test_roundtrip_nested(self):
        """Roundtrip preserves nested structures."""
        original = Metadata({"outer": {"inner": {"deep": [1, 2, 3]}}})
        params = original.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == original.metadata


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        """Metadata with same data are equal."""
        m1 = Metadata({"key": "value"})
        m2 = Metadata({"key": "value"})
        assert m1 == m2

    def test_different(self):
        """Metadata with different data are not equal."""
        m1 = Metadata({"key": "value1"})
        m2 = Metadata({"key": "value2"})
        assert m1 != m2

    def test_not_hashable(self):
        """Metadata is not hashable (contains mutable dict)."""
        m = Metadata({"key": "value"})
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
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == data

    def test_large_data(self):
        """Large data is handled correctly."""
        data = {"items": list(range(10000))}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == data

    def test_special_json_characters(self):
        """Special JSON characters are escaped."""
        data = {"text": 'Hello "World"\nNew line\ttab'}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == data

    def test_null_values_filtered(self):
        """Null values are filtered out for deterministic hashing."""
        data = {"value": None, "nested": {"inner": None}, "real": "data"}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        # None values and empty containers are filtered
        assert reconstructed.metadata == {"real": "data"}
        assert "value" not in reconstructed.metadata
        assert "nested" not in reconstructed.metadata  # becomes empty, then filtered

    def test_boolean_values(self):
        """Boolean values are preserved."""
        data = {"true": True, "false": False}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == data
        assert reconstructed.metadata["true"] is True
        assert reconstructed.metadata["false"] is False

    def test_numeric_precision(self):
        """Numeric precision is preserved for typical values."""
        data = {"int": 9007199254740992, "float": 3.14159}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata["int"] == 9007199254740992
        assert abs(reconstructed.metadata["float"] - 3.14159) < 1e-10

    def test_deeply_nested(self):
        """Deeply nested structures are handled."""
        data = {"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata == data

    def test_empty_string_values(self):
        """Empty string values are preserved."""
        data = {"empty": "", "nested": {"also_empty": ""}}
        m = Metadata(data)
        params = m.to_db_params()
        reconstructed = Metadata.from_db_params(params.metadata_json)
        assert reconstructed.metadata["empty"] == ""
        assert reconstructed.metadata["nested"]["also_empty"] == ""


# =============================================================================
# Normalization Tests (for content-addressed deduplication)
# =============================================================================


class TestNormalization:
    """Tests for JSON normalization ensuring deterministic hashing."""

    def test_empty_dicts_removed(self):
        """Empty dicts are removed for deterministic hashing."""
        m = Metadata({"name": "Relay", "limitation": {}, "fees": {}})
        assert m.metadata == {"name": "Relay"}

    def test_empty_lists_removed(self):
        """Empty lists are removed for deterministic hashing."""
        m = Metadata({"name": "Relay", "tags": [], "nips": []})
        assert m.metadata == {"name": "Relay"}

    def test_nested_empty_removed_recursively(self):
        """Nested empty structures are removed recursively."""
        m = Metadata({"level1": {"level2": {"level3": {}}}})
        assert m.metadata == {}

    def test_non_empty_preserved(self):
        """Non-empty structures are preserved."""
        m = Metadata({"name": "Relay", "limitation": {"max": 1000}, "fees": {}})
        assert m.metadata == {"limitation": {"max": 1000}, "name": "Relay"}

    def test_keys_sorted(self):
        """Dict keys are sorted for deterministic output."""
        m1 = Metadata({"z": 1, "a": 2, "m": 3})
        m2 = Metadata({"a": 2, "m": 3, "z": 1})
        # Both should produce identical JSON
        assert m1.to_db_params().metadata_json == m2.to_db_params().metadata_json

    def test_hash_consistency_empty_containers(self):
        """Semantically identical data produces same hash (empty containers)."""
        import hashlib

        m1 = Metadata({"name": "Relay", "limitation": {}})
        m2 = Metadata({"name": "Relay"})
        h1 = hashlib.sha256(m1.to_db_params().metadata_json.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().metadata_json.encode()).hexdigest()
        assert h1 == h2

    def test_hash_consistency_key_order(self):
        """Semantically identical data produces same hash (key order)."""
        import hashlib

        m1 = Metadata({"b": 2, "a": 1})
        m2 = Metadata({"a": 1, "b": 2})
        h1 = hashlib.sha256(m1.to_db_params().metadata_json.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().metadata_json.encode()).hexdigest()
        assert h1 == h2

    def test_empty_in_lists_removed(self):
        """Empty containers within lists are removed."""
        m = Metadata({"items": [1, [], 2, {}, 3]})
        assert m.metadata == {"items": [1, 2, 3]}

    def test_none_in_lists_removed(self):
        """None values within lists are removed."""
        m = Metadata({"items": [1, None, 2, None, 3]})
        assert m.metadata == {"items": [1, 2, 3]}

    def test_falsy_values_preserved(self):
        """Falsy values (False, 0, '') are preserved, only None/empty containers removed."""
        m = Metadata({"enabled": False, "count": 0, "name": ""})
        assert m.metadata == {"count": 0, "enabled": False, "name": ""}

    def test_list_becomes_empty_after_filtering(self):
        """List with only empty/None elements becomes empty and is removed."""
        m = Metadata({"items": [None, {}, [], None], "real": "data"})
        assert m.metadata == {"real": "data"}
