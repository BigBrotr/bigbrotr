"""
Unit tests for utils.parsing module.

Tests:
- parse_typed_dict() - TypedDict schema validation and parsing
"""

from typing import TypedDict

from utils.parsing import parse_typed_dict


# Test TypedDict schemas
class SimpleSchema(TypedDict, total=False):
    """Simple schema with basic types."""

    name: str
    count: int
    score: float
    active: bool


class ListSchema(TypedDict, total=False):
    """Schema with list types."""

    tags: list[str]
    numbers: list[int]
    items: list


class NestedSchema(TypedDict, total=False):
    """Schema with nested TypedDict."""

    info: SimpleSchema


class ListOfTypedDictSchema(TypedDict, total=False):
    """Schema with list of TypedDict."""

    records: list[SimpleSchema]


class TestParseTypedDictBasicTypes:
    """parse_typed_dict() with basic types."""

    def test_valid_string(self):
        result = parse_typed_dict({"name": "test"}, SimpleSchema)
        assert result["name"] == "test"

    def test_valid_int(self):
        result = parse_typed_dict({"count": 42}, SimpleSchema)
        assert result["count"] == 42

    def test_valid_float(self):
        result = parse_typed_dict({"score": 3.14}, SimpleSchema)
        assert result["score"] == 3.14

    def test_valid_bool(self):
        result = parse_typed_dict({"active": True}, SimpleSchema)
        assert result["active"] is True

    def test_all_fields_present(self):
        data = {"name": "test", "count": 10, "score": 1.5, "active": False}
        result = parse_typed_dict(data, SimpleSchema)
        assert result == data


class TestParseTypedDictMissingValues:
    """parse_typed_dict() handles missing values."""

    def test_missing_value_is_none(self):
        result = parse_typed_dict({}, SimpleSchema)
        assert result["name"] is None
        assert result["count"] is None
        assert result["score"] is None
        assert result["active"] is None

    def test_all_schema_keys_present(self):
        result = parse_typed_dict({}, SimpleSchema)
        assert set(result.keys()) == {"name", "count", "score", "active"}

    def test_partial_data(self):
        result = parse_typed_dict({"name": "test"}, SimpleSchema)
        assert result["name"] == "test"
        assert result["count"] is None


class TestParseTypedDictInvalidTypes:
    """parse_typed_dict() handles invalid types."""

    def test_wrong_type_string_to_int(self):
        result = parse_typed_dict({"count": "not_an_int"}, SimpleSchema)
        assert result["count"] is None

    def test_wrong_type_int_to_string(self):
        result = parse_typed_dict({"name": 123}, SimpleSchema)
        assert result["name"] is None

    def test_wrong_type_string_to_float(self):
        result = parse_typed_dict({"score": "not_a_float"}, SimpleSchema)
        assert result["score"] is None

    def test_wrong_type_int_to_bool(self):
        # Note: in Python, bool is subclass of int, so 1/0 are valid bools
        # But str "true" is not
        result = parse_typed_dict({"active": "true"}, SimpleSchema)
        assert result["active"] is None


class TestParseTypedDictEmptyStrings:
    """parse_typed_dict() normalizes empty strings."""

    def test_empty_string_is_none(self):
        result = parse_typed_dict({"name": ""}, SimpleSchema)
        assert result["name"] is None

    def test_whitespace_only_is_none(self):
        result = parse_typed_dict({"name": "   "}, SimpleSchema)
        assert result["name"] is None

    def test_tabs_and_newlines_is_none(self):
        result = parse_typed_dict({"name": "\t\n  "}, SimpleSchema)
        assert result["name"] is None

    def test_string_with_content_preserved(self):
        result = parse_typed_dict({"name": "  test  "}, SimpleSchema)
        assert result["name"] == "  test  "  # Content preserved, not stripped


class TestParseTypedDictListTypes:
    """parse_typed_dict() with list types."""

    def test_valid_string_list(self):
        result = parse_typed_dict({"tags": ["a", "b", "c"]}, ListSchema)
        assert result["tags"] == ["a", "b", "c"]

    def test_valid_int_list(self):
        result = parse_typed_dict({"numbers": [1, 2, 3]}, ListSchema)
        assert result["numbers"] == [1, 2, 3]

    def test_empty_list_is_none(self):
        result = parse_typed_dict({"tags": []}, ListSchema)
        assert result["tags"] is None

    def test_non_list_is_none(self):
        result = parse_typed_dict({"tags": "not_a_list"}, ListSchema)
        assert result["tags"] is None

    def test_list_without_type_arg(self):
        result = parse_typed_dict({"items": [1, "two", 3.0]}, ListSchema)
        assert result["items"] == [1, "two", 3.0]

    def test_list_without_type_arg_empty_preserved(self):
        # Note: bare 'list' type is not handled as a list type by parse_typed_dict
        # because get_origin(list) returns None. It passes isinstance check.
        result = parse_typed_dict({"items": []}, ListSchema)
        assert result["items"] == []


class TestParseTypedDictListFiltering:
    """parse_typed_dict() filters invalid list elements."""

    def test_filters_wrong_type_elements(self):
        result = parse_typed_dict({"tags": ["valid", 123, "also_valid"]}, ListSchema)
        assert result["tags"] == ["valid", "also_valid"]

    def test_filters_none_elements(self):
        result = parse_typed_dict({"tags": ["a", None, "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_empty_string_elements(self):
        result = parse_typed_dict({"tags": ["a", "", "b", "   "]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_all_invalid_elements_returns_none(self):
        result = parse_typed_dict({"tags": [123, None, ""]}, ListSchema)
        assert result["tags"] is None

    def test_filters_empty_nested_iterables(self):
        # List elements that are empty lists/dicts are filtered
        result = parse_typed_dict({"tags": ["a", [], "b", {}]}, ListSchema)
        assert result["tags"] == ["a", "b"]


class TestParseTypedDictNestedTypedDict:
    """parse_typed_dict() handles nested TypedDict fields."""

    def test_nested_typeddict_is_none(self):
        # Nested TypedDict fields are set to None for caller to handle
        result = parse_typed_dict({"info": {"name": "test", "count": 10}}, NestedSchema)
        assert result["info"] is None

    def test_list_of_typeddict_is_none(self):
        # List of TypedDict is set to None for caller to handle
        result = parse_typed_dict(
            {"records": [{"name": "a"}, {"name": "b"}]}, ListOfTypedDictSchema
        )
        assert result["records"] is None


class TestParseTypedDictExtraKeys:
    """parse_typed_dict() ignores extra keys not in schema."""

    def test_extra_keys_ignored(self):
        result = parse_typed_dict(
            {"name": "test", "extra": "ignored", "another": 123}, SimpleSchema
        )
        assert "extra" not in result
        assert "another" not in result
        assert result["name"] == "test"

    def test_only_schema_keys_in_result(self):
        result = parse_typed_dict({"unknown": "value"}, SimpleSchema)
        assert set(result.keys()) == {"name", "count", "score", "active"}


class TestParseTypedDictEdgeCases:
    """parse_typed_dict() edge cases."""

    def test_none_value_explicit(self):
        result = parse_typed_dict({"name": None}, SimpleSchema)
        assert result["name"] is None

    def test_zero_int_preserved(self):
        result = parse_typed_dict({"count": 0}, SimpleSchema)
        assert result["count"] == 0

    def test_zero_float_preserved(self):
        result = parse_typed_dict({"score": 0.0}, SimpleSchema)
        assert result["score"] == 0.0

    def test_false_bool_preserved(self):
        result = parse_typed_dict({"active": False}, SimpleSchema)
        assert result["active"] is False

    def test_negative_numbers_preserved(self):
        result = parse_typed_dict({"count": -5, "score": -3.14}, SimpleSchema)
        assert result["count"] == -5
        assert result["score"] == -3.14
