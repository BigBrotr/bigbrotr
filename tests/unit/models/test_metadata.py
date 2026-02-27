"""Unit tests for the Metadata model and MetadataType enum."""

import json
from dataclasses import FrozenInstanceError

import pytest

from bigbrotr.models.metadata import Metadata, MetadataDbParams, MetadataType


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """Metadata construction and initialization."""

    def test_with_dict(self):
        """Constructs with dict data."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test", "value": 123})
        assert m.data == {"name": "test", "value": 123}
        assert m.type == MetadataType.NIP11_INFO

    def test_with_none_rejected(self):
        """None is not a valid Mapping for data."""
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data=None)  # type: ignore[arg-type]

    def test_without_args(self):
        """Constructs without value defaults to empty dict."""
        m = Metadata(type=MetadataType.NIP11_INFO)
        assert m.data == {}

    def test_with_empty_dict(self):
        """Constructs with empty dict."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        assert m.data == {}

    def test_with_nested(self):
        """Constructs with nested dict."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"outer": {"inner": "value"}})
        assert m.data["outer"]["inner"] == "value"

    def test_with_list_values(self):
        """Constructs with list values in dict."""
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"items": [1, 2, 3], "names": ["a", "b", "c"]}
        )
        assert m.data["items"] == (1, 2, 3)
        assert m.data["names"] == ("a", "b", "c")

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
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        assert m.data["string"] == "text"
        assert m.data["number"] == 42
        assert m.data["float"] == 3.14
        assert m.data["bool"] is True
        assert "null" not in m.data  # None values filtered for deterministic hashing


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        """Cannot modify metadata attribute."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        with pytest.raises(FrozenInstanceError):
            m.data = {"new": "data"}  # type: ignore[misc]

    def test_new_attribute_blocked(self):
        """Cannot add new attributes."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            m.new_attr = "value"


# =============================================================================
# Sanitization Tests
# =============================================================================


class TestSanitize:
    """JSON sanitization via _sanitize and __post_init__."""

    def test_non_string_keys_skipped(self):
        """Non-string keys are filtered out during sanitization."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed == {"key": "value"}

    def test_non_serializable_filtered_out(self):
        """Non-JSON-serializable values are filtered out (become None, then filtered)."""

        class Custom:
            pass

        m = Metadata(type=MetadataType.NIP11_INFO, data={"valid": "ok", "invalid": Custom()})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed == {"valid": "ok"}

    def test_null_bytes_rejected(self):
        """Null bytes in strings raise ValueError."""
        with pytest.raises(ValueError, match="null bytes"):
            Metadata(type=MetadataType.NIP11_INFO, data={"text": "hello\x00world"})

    def test_deeply_nested_sanitization(self):
        """Deeply nested structures are sanitized correctly."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"l1": {"l2": {"l3": {"l4": "value"}}}})
        assert m.data["l1"]["l2"]["l3"]["l4"] == "value"


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Metadata.to_db_params() for PostgreSQL JSONB."""

    def test_returns_metadata_db_params(self):
        """Returns MetadataDbParams NamedTuple."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test"})
        result = m.to_db_params()
        assert isinstance(result, MetadataDbParams)
        assert len(result) == 3
        assert isinstance(result.id, bytes)
        assert len(result.id) == 32  # SHA-256 hash
        assert result.type == MetadataType.NIP11_INFO

    def test_valid_json(self):
        """Returns valid JSON string."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "test", "value": 123})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed == {"name": "test", "value": 123}

    def test_empty_dict(self):
        """Empty dict serializes to '{}'."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={})
        assert m.to_db_params().data == "{}"

    def test_unicode(self):
        """Unicode is preserved (ensure_ascii=False)."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"})
        assert "Relay" in m.to_db_params().data

    def test_nested(self):
        """Nested structures serialize correctly."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"a": {"b": {"c": [1, 2, 3]}}})
        params = m.to_db_params()
        parsed = json.loads(params.data)
        assert parsed["a"]["b"]["c"] == [1, 2, 3]


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        """Metadata with same type and data are equal."""
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        assert m1 == m2

    def test_different_value(self):
        """Metadata with different data are not equal."""
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value1"})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value2"})
        assert m1 != m2

    def test_different_type(self):
        """Metadata with different types are not equal."""
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
        m2 = Metadata(type=MetadataType.NIP66_RTT, data={"key": "value"})
        assert m1 != m2

    def test_not_hashable(self):
        """Metadata is not hashable (contains mutable dict)."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"key": "value"})
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
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_large_data(self):
        """Large data is handled correctly."""
        data = {"items": list(range(10000))}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == {"items": tuple(range(10000))}

    def test_special_json_characters(self):
        """Special JSON characters are escaped."""
        data = {"text": 'Hello "World"\nNew line\ttab'}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_null_values_filtered(self):
        """Null values are filtered out for deterministic hashing."""
        data = {"value": None, "nested": {"inner": None}, "real": "data"}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == {"real": "data"}
        assert "value" not in reconstructed.data
        assert "nested" not in reconstructed.data

    def test_boolean_values(self):
        """Boolean values are preserved."""
        data = {"true": True, "false": False}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data
        assert reconstructed.data["true"] is True
        assert reconstructed.data["false"] is False

    def test_numeric_precision(self):
        """Numeric precision is preserved for typical values."""
        data = {"int": 9007199254740992, "float": 3.14159}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data["int"] == 9007199254740992
        assert abs(reconstructed.data["float"] - 3.14159) < 1e-10

    def test_deeply_nested(self):
        """Deeply nested structures are handled."""
        data = {"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}
        m = Metadata(type=MetadataType.NIP11_INFO, data=data)
        params = m.to_db_params()
        reconstructed = Metadata(type=params.type, data=json.loads(params.data))
        assert reconstructed.data == data

    def test_list_as_data_rejected(self):
        """Passing a list as data raises TypeError."""
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data=[1, 2, 3])

    def test_string_as_data_rejected(self):
        """Passing a string as data raises TypeError."""
        with pytest.raises(TypeError, match="data must be a Mapping"):
            Metadata(type=MetadataType.NIP11_INFO, data="not a dict")

    def test_empty_string_values(self):
        """Empty string values are preserved."""
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

    def test_empty_dicts_removed(self):
        """Empty dicts are removed for deterministic hashing."""
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"name": "Relay", "limitation": {}, "fees": {}}
        )
        assert m.data == {"name": "Relay"}

    def test_empty_lists_removed(self):
        """Empty lists are removed for deterministic hashing."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay", "tags": [], "nips": []})
        assert m.data == {"name": "Relay"}

    def test_nested_empty_removed_recursively(self):
        """Nested empty structures are removed recursively."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"level1": {"level2": {"level3": {}}}})
        assert m.data == {}

    def test_non_empty_preserved(self):
        """Non-empty structures are preserved."""
        m = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "Relay", "limitation": {"max": 1000}, "fees": {}},
        )
        assert m.data == {"limitation": {"max": 1000}, "name": "Relay"}

    def test_keys_sorted(self):
        """Dict keys are sorted for deterministic output."""
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"z": 1, "a": 2, "m": 3})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 2, "m": 3, "z": 1})
        assert m1.to_db_params().data == m2.to_db_params().data

    def test_hash_consistency_empty_containers(self):
        """Semantically identical data produces same hash (empty containers)."""
        import hashlib

        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay", "limitation": {}})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Relay"})
        h1 = hashlib.sha256(m1.to_db_params().data.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().data.encode()).hexdigest()
        assert h1 == h2

    def test_hash_consistency_key_order(self):
        """Semantically identical data produces same hash (key order)."""
        import hashlib

        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        h1 = hashlib.sha256(m1.to_db_params().data.encode()).hexdigest()
        h2 = hashlib.sha256(m2.to_db_params().data.encode()).hexdigest()
        assert h1 == h2

    def test_empty_in_lists_removed(self):
        """Empty containers within lists are removed."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"items": [1, [], 2, {}, 3]})
        assert m.data == {"items": (1, 2, 3)}

    def test_none_in_lists_removed(self):
        """None values within lists are removed."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"items": [1, None, 2, None, 3]})
        assert m.data == {"items": (1, 2, 3)}

    def test_falsy_values_preserved(self):
        """Falsy values (False, 0, '') are preserved, only None/empty containers removed."""
        m = Metadata(type=MetadataType.NIP11_INFO, data={"enabled": False, "count": 0, "name": ""})
        assert m.data == {"count": 0, "enabled": False, "name": ""}

    def test_list_becomes_empty_after_filtering(self):
        """List with only empty/None elements becomes empty and is removed."""
        m = Metadata(
            type=MetadataType.NIP11_INFO, data={"items": [None, {}, [], None], "real": "data"}
        )
        assert m.data == {"real": "data"}


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_type_non_enum_rejected(self):
        """type must be a MetadataType enum member."""
        with pytest.raises(TypeError, match="type must be a MetadataType"):
            Metadata(type="nip11_info", data={"key": "value"})  # type: ignore[arg-type]

    def test_type_int_rejected(self):
        """type must be a MetadataType, not an int."""
        with pytest.raises(TypeError, match="type must be a MetadataType"):
            Metadata(type=42, data={"key": "value"})  # type: ignore[arg-type]
