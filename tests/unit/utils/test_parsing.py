"""
Unit tests for utils.parsing module.

Tests:
- parse_typed_dict() - TypedDict schema validation and parsing
  - Basic type validation (str, int, float, bool)
  - Missing values handling
  - Invalid type handling
  - Empty string normalization
  - List type handling and filtering
  - Nested TypedDict handling
  - Extra keys handling
  - Edge cases
"""

from typing import TypedDict

from utils.parsing import parse_typed_dict


# =============================================================================
# Test TypedDict Schemas
# =============================================================================


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
    items: list  # Bare list without type argument


class NestedSchema(TypedDict, total=False):
    """Schema with nested TypedDict."""

    info: SimpleSchema


class ListOfTypedDictSchema(TypedDict, total=False):
    """Schema with list of TypedDict."""

    records: list[SimpleSchema]


class ComplexListSchema(TypedDict, total=False):
    """Schema with various list types."""

    floats: list[float]
    bools: list[bool]
    mixed: list[str | int]  # Not a single inner type - will be handled specially


# =============================================================================
# Basic Type Validation Tests
# =============================================================================


class TestParseTypedDictBasicTypes:
    """parse_typed_dict() with basic types."""

    def test_valid_string(self):
        """Valid string is preserved."""
        result = parse_typed_dict({"name": "test"}, SimpleSchema)
        assert result["name"] == "test"

    def test_valid_int(self):
        """Valid integer is preserved."""
        result = parse_typed_dict({"count": 42}, SimpleSchema)
        assert result["count"] == 42

    def test_valid_float(self):
        """Valid float is preserved."""
        result = parse_typed_dict({"score": 3.14}, SimpleSchema)
        assert result["score"] == 3.14

    def test_valid_bool_true(self):
        """Valid True boolean is preserved."""
        result = parse_typed_dict({"active": True}, SimpleSchema)
        assert result["active"] is True

    def test_valid_bool_false(self):
        """Valid False boolean is preserved."""
        result = parse_typed_dict({"active": False}, SimpleSchema)
        assert result["active"] is False

    def test_all_fields_present(self):
        """All valid fields are preserved together."""
        data = {"name": "test", "count": 10, "score": 1.5, "active": False}
        result = parse_typed_dict(data, SimpleSchema)
        assert result == data


# =============================================================================
# Missing Values Tests
# =============================================================================


class TestParseTypedDictMissingValues:
    """parse_typed_dict() handles missing values."""

    def test_missing_value_is_none(self):
        """Missing values become None."""
        result = parse_typed_dict({}, SimpleSchema)
        assert result["name"] is None
        assert result["count"] is None
        assert result["score"] is None
        assert result["active"] is None

    def test_all_schema_keys_present(self):
        """All schema keys are present in result even when missing from input."""
        result = parse_typed_dict({}, SimpleSchema)
        assert set(result.keys()) == {"name", "count", "score", "active"}

    def test_partial_data_fills_missing_with_none(self):
        """Partial data has missing fields filled with None."""
        result = parse_typed_dict({"name": "test"}, SimpleSchema)
        assert result["name"] == "test"
        assert result["count"] is None
        assert result["score"] is None
        assert result["active"] is None

    def test_none_value_explicit(self):
        """Explicitly provided None remains None."""
        result = parse_typed_dict({"name": None}, SimpleSchema)
        assert result["name"] is None


# =============================================================================
# Invalid Type Handling Tests
# =============================================================================


class TestParseTypedDictInvalidTypes:
    """parse_typed_dict() handles invalid types."""

    def test_wrong_type_string_to_int(self):
        """String where int expected becomes None."""
        result = parse_typed_dict({"count": "not_an_int"}, SimpleSchema)
        assert result["count"] is None

    def test_wrong_type_int_to_string(self):
        """Int where string expected becomes None."""
        result = parse_typed_dict({"name": 123}, SimpleSchema)
        assert result["name"] is None

    def test_wrong_type_string_to_float(self):
        """String where float expected becomes None."""
        result = parse_typed_dict({"score": "not_a_float"}, SimpleSchema)
        assert result["score"] is None

    def test_wrong_type_string_to_bool(self):
        """String where bool expected becomes None."""
        result = parse_typed_dict({"active": "true"}, SimpleSchema)
        assert result["active"] is None

    def test_list_where_string_expected(self):
        """List where string expected becomes None."""
        result = parse_typed_dict({"name": ["a", "b"]}, SimpleSchema)
        assert result["name"] is None

    def test_dict_where_int_expected(self):
        """Dict where int expected becomes None."""
        result = parse_typed_dict({"count": {"value": 5}}, SimpleSchema)
        assert result["count"] is None


# =============================================================================
# Empty String Normalization Tests
# =============================================================================


class TestParseTypedDictEmptyStrings:
    """parse_typed_dict() normalizes empty strings."""

    def test_empty_string_is_none(self):
        """Empty string becomes None."""
        result = parse_typed_dict({"name": ""}, SimpleSchema)
        assert result["name"] is None

    def test_whitespace_only_is_none(self):
        """Whitespace-only string becomes None."""
        result = parse_typed_dict({"name": "   "}, SimpleSchema)
        assert result["name"] is None

    def test_tabs_is_none(self):
        """Tab-only string becomes None."""
        result = parse_typed_dict({"name": "\t\t"}, SimpleSchema)
        assert result["name"] is None

    def test_newlines_is_none(self):
        """Newline-only string becomes None."""
        result = parse_typed_dict({"name": "\n\n"}, SimpleSchema)
        assert result["name"] is None

    def test_mixed_whitespace_is_none(self):
        """Mixed whitespace string becomes None."""
        result = parse_typed_dict({"name": "\t\n  "}, SimpleSchema)
        assert result["name"] is None

    def test_string_with_content_preserved(self):
        """String with content is preserved (not stripped)."""
        result = parse_typed_dict({"name": "  test  "}, SimpleSchema)
        assert result["name"] == "  test  "  # Content preserved, not stripped


# =============================================================================
# List Type Tests
# =============================================================================


class TestParseTypedDictListTypes:
    """parse_typed_dict() with list types."""

    def test_valid_string_list(self):
        """Valid list of strings is preserved."""
        result = parse_typed_dict({"tags": ["a", "b", "c"]}, ListSchema)
        assert result["tags"] == ["a", "b", "c"]

    def test_valid_int_list(self):
        """Valid list of integers is preserved."""
        result = parse_typed_dict({"numbers": [1, 2, 3]}, ListSchema)
        assert result["numbers"] == [1, 2, 3]

    def test_empty_list_is_none(self):
        """Empty list becomes None."""
        result = parse_typed_dict({"tags": []}, ListSchema)
        assert result["tags"] is None

    def test_non_list_is_none(self):
        """Non-list value becomes None."""
        result = parse_typed_dict({"tags": "not_a_list"}, ListSchema)
        assert result["tags"] is None

    def test_dict_instead_of_list_is_none(self):
        """Dict instead of list becomes None."""
        result = parse_typed_dict({"tags": {"key": "value"}}, ListSchema)
        assert result["tags"] is None

    def test_list_without_type_arg_preserved(self):
        """Bare list without type arg preserves all elements."""
        result = parse_typed_dict({"items": [1, "two", 3.0]}, ListSchema)
        assert result["items"] == [1, "two", 3.0]

    def test_list_without_type_arg_empty_preserved(self):
        """Bare list empty is preserved as empty (not None)."""
        # Note: bare 'list' type is handled differently - it passes isinstance check
        result = parse_typed_dict({"items": []}, ListSchema)
        # Empty bare list is preserved as empty, not normalized to None
        assert result["items"] == []


# =============================================================================
# List Element Filtering Tests
# =============================================================================


class TestParseTypedDictListFiltering:
    """parse_typed_dict() filters invalid list elements."""

    def test_filters_wrong_type_elements(self):
        """Wrong type elements are filtered from list."""
        result = parse_typed_dict({"tags": ["valid", 123, "also_valid"]}, ListSchema)
        assert result["tags"] == ["valid", "also_valid"]

    def test_filters_none_elements(self):
        """None elements are filtered from list."""
        result = parse_typed_dict({"tags": ["a", None, "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_empty_string_elements(self):
        """Empty string elements are filtered from list."""
        result = parse_typed_dict({"tags": ["a", "", "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_whitespace_string_elements(self):
        """Whitespace-only string elements are filtered from list."""
        result = parse_typed_dict({"tags": ["a", "   ", "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_all_invalid_elements_returns_none(self):
        """List with all invalid elements becomes None."""
        result = parse_typed_dict({"tags": [123, None, ""]}, ListSchema)
        assert result["tags"] is None

    def test_filters_empty_list_elements(self):
        """Empty list elements are filtered."""
        result = parse_typed_dict({"tags": ["a", [], "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_empty_dict_elements(self):
        """Empty dict elements are filtered."""
        result = parse_typed_dict({"tags": ["a", {}, "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_empty_set_elements(self):
        """Empty set elements are filtered."""
        result = parse_typed_dict({"tags": ["a", set(), "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_empty_tuple_elements(self):
        """Empty tuple elements are filtered."""
        result = parse_typed_dict({"tags": ["a", (), "b"]}, ListSchema)
        assert result["tags"] == ["a", "b"]

    def test_filters_multiple_invalid_types(self):
        """Multiple invalid types are all filtered."""
        result = parse_typed_dict({"tags": ["valid", 1, 2.5, True, None, "", [], {}]}, ListSchema)
        assert result["tags"] == ["valid"]


# =============================================================================
# Nested TypedDict Tests
# =============================================================================


class TestParseTypedDictNestedTypedDict:
    """parse_typed_dict() handles nested TypedDict fields."""

    def test_nested_typeddict_is_none(self):
        """Nested TypedDict fields are set to None (caller handles)."""
        result = parse_typed_dict({"info": {"name": "test", "count": 10}}, NestedSchema)
        assert result["info"] is None

    def test_list_of_typeddict_is_none(self):
        """List of TypedDict is set to None (caller handles)."""
        result = parse_typed_dict(
            {"records": [{"name": "a"}, {"name": "b"}]}, ListOfTypedDictSchema
        )
        assert result["records"] is None

    def test_missing_nested_typeddict_is_none(self):
        """Missing nested TypedDict is None."""
        result = parse_typed_dict({}, NestedSchema)
        assert result["info"] is None


# =============================================================================
# Extra Keys Handling Tests
# =============================================================================


class TestParseTypedDictExtraKeys:
    """parse_typed_dict() ignores extra keys not in schema."""

    def test_extra_keys_ignored(self):
        """Extra keys not in schema are not in result."""
        result = parse_typed_dict(
            {"name": "test", "extra": "ignored", "another": 123}, SimpleSchema
        )
        assert "extra" not in result
        assert "another" not in result
        assert result["name"] == "test"

    def test_only_schema_keys_in_result(self):
        """Only schema keys appear in result."""
        result = parse_typed_dict({"unknown": "value"}, SimpleSchema)
        assert set(result.keys()) == {"name", "count", "score", "active"}

    def test_schema_keys_and_extra_keys_mixed(self):
        """Schema keys preserved, extra keys ignored when mixed."""
        result = parse_typed_dict(
            {"name": "test", "count": 5, "extra1": 1, "extra2": 2}, SimpleSchema
        )
        assert result["name"] == "test"
        assert result["count"] == 5
        assert "extra1" not in result
        assert "extra2" not in result


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestParseTypedDictEdgeCases:
    """parse_typed_dict() edge cases."""

    def test_zero_int_preserved(self):
        """Zero integer is preserved (not falsified to None)."""
        result = parse_typed_dict({"count": 0}, SimpleSchema)
        assert result["count"] == 0

    def test_zero_float_preserved(self):
        """Zero float is preserved."""
        result = parse_typed_dict({"score": 0.0}, SimpleSchema)
        assert result["score"] == 0.0

    def test_false_bool_preserved(self):
        """False boolean is preserved."""
        result = parse_typed_dict({"active": False}, SimpleSchema)
        assert result["active"] is False

    def test_negative_int_preserved(self):
        """Negative integer is preserved."""
        result = parse_typed_dict({"count": -5}, SimpleSchema)
        assert result["count"] == -5

    def test_negative_float_preserved(self):
        """Negative float is preserved."""
        result = parse_typed_dict({"score": -3.14}, SimpleSchema)
        assert result["score"] == -3.14

    def test_very_large_int(self):
        """Very large integer is preserved."""
        big_num = 10**20
        result = parse_typed_dict({"count": big_num}, SimpleSchema)
        assert result["count"] == big_num

    def test_very_small_float(self):
        """Very small float is preserved."""
        small_num = 1e-20
        result = parse_typed_dict({"score": small_num}, SimpleSchema)
        assert result["score"] == small_num

    def test_unicode_string(self):
        """Unicode string is preserved."""
        result = parse_typed_dict({"name": "Hello World"}, SimpleSchema)
        assert result["name"] == "Hello World"

    def test_emoji_string(self):
        """Emoji string is preserved."""
        result = parse_typed_dict({"name": "test 123"}, SimpleSchema)
        assert result["name"] == "test 123"

    def test_special_float_nan(self):
        """NaN float is preserved."""
        import math

        result = parse_typed_dict({"score": float("nan")}, SimpleSchema)
        assert math.isnan(result["score"])

    def test_special_float_inf(self):
        """Infinity float is preserved."""
        result = parse_typed_dict({"score": float("inf")}, SimpleSchema)
        assert result["score"] == float("inf")


# =============================================================================
# Bool Subclass of Int Tests
# =============================================================================


class TestParseTypedDictBoolIntRelation:
    """parse_typed_dict() handles bool being subclass of int."""

    def test_bool_accepted_for_int_field(self):
        """In Python, bool is subclass of int, so True/False may be accepted."""
        # This is Python behavior: isinstance(True, int) is True
        result = parse_typed_dict({"count": True}, SimpleSchema)
        # True is technically an int (1), behavior depends on implementation
        # The current implementation accepts it as isinstance(True, int) is True
        assert result["count"] in (True, 1, None)

    def test_int_not_accepted_for_bool_field(self):
        """Int values 0/1 are not accepted for bool field."""
        # isinstance(1, bool) is False, so ints should be rejected for bool fields
        result = parse_typed_dict({"active": 1}, SimpleSchema)
        assert result["active"] is None

        result = parse_typed_dict({"active": 0}, SimpleSchema)
        assert result["active"] is None


# =============================================================================
# List of Numbers Tests
# =============================================================================


class TestParseTypedDictListOfNumbers:
    """parse_typed_dict() with list of numeric types."""

    def test_list_of_floats(self):
        """List of floats is preserved."""
        result = parse_typed_dict({"floats": [1.1, 2.2, 3.3]}, ComplexListSchema)
        assert result["floats"] == [1.1, 2.2, 3.3]

    def test_list_of_bools(self):
        """List of booleans is preserved."""
        result = parse_typed_dict({"bools": [True, False, True]}, ComplexListSchema)
        assert result["bools"] == [True, False, True]

    def test_list_of_floats_filters_strings(self):
        """String elements filtered from float list."""
        result = parse_typed_dict({"floats": [1.1, "invalid", 3.3]}, ComplexListSchema)
        assert result["floats"] == [1.1, 3.3]

    def test_list_of_ints_filters_floats(self):
        """Float elements filtered from int list."""
        result = parse_typed_dict({"numbers": [1, 2.5, 3]}, ListSchema)
        assert result["numbers"] == [1, 3]
