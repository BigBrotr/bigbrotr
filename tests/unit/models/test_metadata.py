"""
Unit tests for models.metadata module.

Tests:
- Construction from dict
- Immutability enforcement
- JSON serialization (to_db_params method)
- Type-safe getters (_get, _get_optional, _get_nested)
- Equality and hashing
"""

import json

import pytest

from models import Metadata


class TestConstruction:
    """Construction and initialization."""

    def test_with_dict(self):
        m = Metadata({"name": "test", "value": 123})
        assert m.data == {"name": "test", "value": 123}

    def test_with_none(self):
        m = Metadata(None)
        assert m.data == {}

    def test_without_args(self):
        m = Metadata()
        assert m.data == {}

    def test_with_nested(self):
        m = Metadata({"outer": {"inner": "value"}})
        assert m.data["outer"]["inner"] == "value"


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        m = Metadata({"key": "value"})
        with pytest.raises(AttributeError):
            m.data = {"new": "data"}

    def test_new_attribute_blocked(self):
        m = Metadata({})
        with pytest.raises((AttributeError, TypeError)):
            m.new_attr = "value"


class TestGetMethods:
    """Type-safe getter methods."""

    def test_get_with_default(self):
        m = Metadata({"name": "test"})
        assert m._get("name", expected_type=str, default="default") == "test"

    def test_get_wrong_type_returns_default(self):
        m = Metadata({"name": 123})
        assert m._get("name", expected_type=str, default="default") == "default"

    def test_get_missing_returns_default(self):
        m = Metadata({})
        assert m._get("missing", expected_type=str, default="default") == "default"

    def test_get_optional_exists(self):
        m = Metadata({"name": "test"})
        assert m._get("name", expected_type=str) == "test"

    def test_get_optional_wrong_type(self):
        m = Metadata({"name": 123})
        assert m._get("name", expected_type=str) is None

    def test_get_optional_missing(self):
        m = Metadata({})
        assert m._get("missing", expected_type=str) is None

    def test_get_nested_with_default(self):
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str, default="default") == "value"

    def test_get_nested_missing_outer(self):
        m = Metadata({})
        assert m._get("missing", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_outer_not_dict(self):
        m = Metadata({"outer": "not_a_dict"})
        assert m._get("outer", "inner", expected_type=str, default="default") == "default"

    def test_get_nested_optional_exists(self):
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get("outer", "inner", expected_type=str) == "value"

    def test_get_nested_optional_missing(self):
        m = Metadata({})
        assert m._get("missing", "inner", expected_type=str) is None

    def test_get_deep_nested(self):
        m = Metadata({"a": {"b": {"c": "deep"}}})
        assert m._get("a", "b", "c", expected_type=str) == "deep"

    def test_get_deep_nested_with_default(self):
        m = Metadata({"a": {"b": {}}})
        assert m._get("a", "b", "c", expected_type=str, default="fallback") == "fallback"


class TestSanitize:
    """JSON sanitization via to_db_params."""

    def test_non_string_keys_skipped(self):
        m = Metadata({"key": "value", 123: "skipped"})  # type: ignore[dict-item]
        parsed = json.loads(m.to_db_params()[0])
        assert parsed == {"key": "value"}

    def test_non_serializable_becomes_none(self):
        class Custom:
            pass

        m = Metadata({"valid": "ok", "invalid": Custom()})
        parsed = json.loads(m.to_db_params()[0])
        assert parsed == {"valid": "ok", "invalid": None}


class TestToDbParams:
    """JSONB serialization for PostgreSQL."""

    def test_returns_tuple(self):
        m = Metadata({"name": "test"})
        result = m.to_db_params()
        assert isinstance(result, tuple)
        assert len(result) == 1

    def test_valid_json(self):
        m = Metadata({"name": "test", "value": 123})
        parsed = json.loads(m.to_db_params()[0])
        assert parsed == {"name": "test", "value": 123}

    def test_empty(self):
        m = Metadata({})
        assert m.to_db_params()[0] == "{}"

    def test_unicode(self):
        m = Metadata({"name": "日本語"})
        assert "日本語" in m.to_db_params()[0]

    def test_nested(self):
        m = Metadata({"a": {"b": {"c": [1, 2, 3]}}})
        parsed = json.loads(m.to_db_params()[0])
        assert parsed["a"]["b"]["c"] == [1, 2, 3]


class TestFromDbParams:
    """Reconstruction from database parameters."""

    def test_simple(self):
        m = Metadata.from_db_params('{"name": "test"}')
        assert m.data == {"name": "test"}

    def test_nested(self):
        m = Metadata.from_db_params('{"a": {"b": [1, 2, 3]}}')
        assert m.data["a"]["b"] == [1, 2, 3]

    def test_empty(self):
        m = Metadata.from_db_params("{}")
        assert m.data == {}

    def test_roundtrip(self):
        """to_db_params -> from_db_params should preserve data."""
        original = Metadata({"name": "test", "value": 123})
        params = original.to_db_params()
        reconstructed = Metadata.from_db_params(params[0])
        assert reconstructed.data == original.data


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        m1 = Metadata({"key": "value"})
        m2 = Metadata({"key": "value"})
        assert m1 == m2

    def test_different(self):
        m1 = Metadata({"key": "value1"})
        m2 = Metadata({"key": "value2"})
        assert m1 != m2

    def test_not_hashable(self):
        m = Metadata({"key": "value"})
        with pytest.raises(TypeError):
            hash(m)
