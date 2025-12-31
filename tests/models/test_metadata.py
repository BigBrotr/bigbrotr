"""Tests for models.metadata module."""

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
        with pytest.raises(AttributeError):
            m.new_attr = "value"


class TestGetMethods:
    """Type-safe getter methods."""

    def test_get_correct_type(self):
        m = Metadata({"name": "test"})
        assert m._get("name", str, "default") == "test"

    def test_get_wrong_type(self):
        m = Metadata({"name": 123})
        assert m._get("name", str, "default") == "default"

    def test_get_missing(self):
        m = Metadata({})
        assert m._get("missing", str, "default") == "default"

    def test_get_optional_exists(self):
        m = Metadata({"name": "test"})
        assert m._get_optional("name", str) == "test"

    def test_get_optional_wrong_type(self):
        m = Metadata({"name": 123})
        assert m._get_optional("name", str) is None

    def test_get_optional_missing(self):
        m = Metadata({})
        assert m._get_optional("missing", str) is None

    def test_get_nested_exists(self):
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get_nested("outer", "inner", str, "default") == "value"

    def test_get_nested_missing_outer(self):
        m = Metadata({})
        assert m._get_nested("missing", "inner", str, "default") == "default"

    def test_get_nested_outer_not_dict(self):
        m = Metadata({"outer": "not_a_dict"})
        assert m._get_nested("outer", "inner", str, "default") == "default"

    def test_get_nested_optional_exists(self):
        m = Metadata({"outer": {"inner": "value"}})
        assert m._get_nested_optional("outer", "inner", str) == "value"

    def test_get_nested_optional_missing(self):
        m = Metadata({})
        assert m._get_nested_optional("missing", "inner", str) is None


class TestSanitize:
    """JSON sanitization for PostgreSQL."""

    def test_primitives(self):
        assert Metadata._sanitize_for_json(None) is None
        assert Metadata._sanitize_for_json(True) is True
        assert Metadata._sanitize_for_json(42) == 42
        assert Metadata._sanitize_for_json(3.14) == 3.14
        assert Metadata._sanitize_for_json("test") == "test"

    def test_dict(self):
        data = {"key": "value", "nested": {"inner": 123}}
        assert Metadata._sanitize_for_json(data) == data

    def test_dict_skips_non_string_keys(self):
        data = {"key": "value", 123: "skipped"}
        assert Metadata._sanitize_for_json(data) == {"key": "value"}

    def test_list(self):
        data = [1, "two", {"three": 3}]
        assert Metadata._sanitize_for_json(data) == data

    def test_tuple_to_list(self):
        assert Metadata._sanitize_for_json((1, 2, 3)) == [1, 2, 3]

    def test_object_to_string(self):
        class Custom:
            def __str__(self):
                return "custom"

        assert Metadata._sanitize_for_json(Custom()) == "custom"


class TestDataJsonb:
    """JSONB serialization for PostgreSQL."""

    def test_valid_json(self):
        m = Metadata({"name": "test", "value": 123})
        parsed = json.loads(m.data_jsonb)
        assert parsed == {"name": "test", "value": 123}

    def test_empty(self):
        m = Metadata({})
        assert m.data_jsonb == "{}"

    def test_unicode(self):
        m = Metadata({"name": "日本語"})
        assert "日本語" in m.data_jsonb

    def test_nested(self):
        m = Metadata({"a": {"b": {"c": [1, 2, 3]}}})
        parsed = json.loads(m.data_jsonb)
        assert parsed["a"]["b"]["c"] == [1, 2, 3]


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
