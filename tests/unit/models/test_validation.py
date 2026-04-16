"""Tests for bigbrotr.models._validation shared helpers."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from bigbrotr.models._validation import (
    deep_freeze,
    normalize_json_data,
    validate_instance,
    validate_json_data,
    validate_mapping,
    validate_str_no_null,
    validate_str_not_empty,
    validate_timestamp,
)


class TestValidateInstance:
    def test_correct_type_passes(self) -> None:
        validate_instance("hello", str, "field")

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got int"):
            validate_instance(42, str, "field")

    def test_none_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be an int, got NoneType"):
            validate_instance(None, int, "field")

    def test_article_an_for_vowel(self) -> None:
        with pytest.raises(TypeError, match="field must be an int"):
            validate_instance("x", int, "field")

    def test_article_a_for_consonant(self) -> None:
        with pytest.raises(TypeError, match="field must be a str"):
            validate_instance(42, str, "field")

    def test_subclass_accepted(self) -> None:
        validate_instance(True, int, "field")


class TestValidateTimestamp:
    def test_zero_accepted(self) -> None:
        validate_timestamp(0, "ts")

    def test_positive_accepted(self) -> None:
        validate_timestamp(1700000000, "ts")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="ts must be non-negative"):
            validate_timestamp(-1, "ts")

    def test_bool_rejected(self) -> None:
        with pytest.raises(TypeError, match="ts must be an int, got bool"):
            validate_timestamp(True, "ts")

    def test_float_rejected(self) -> None:
        with pytest.raises(TypeError, match="ts must be an int, got float"):
            validate_timestamp(1.0, "ts")

    def test_string_rejected(self) -> None:
        with pytest.raises(TypeError, match="ts must be an int, got str"):
            validate_timestamp("123", "ts")

    def test_none_rejected(self) -> None:
        with pytest.raises(TypeError, match="ts must be an int, got NoneType"):
            validate_timestamp(None, "ts")


class TestValidateStrNoNull:
    def test_normal_string_passes(self) -> None:
        validate_str_no_null("hello", "field")

    def test_empty_string_passes(self) -> None:
        validate_str_no_null("", "field")

    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ValueError, match="field contains null bytes"):
            validate_str_no_null("hello\x00world", "field")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got int"):
            validate_str_no_null(42, "field")

    def test_none_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got NoneType"):
            validate_str_no_null(None, "field")

    def test_bytes_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got bytes"):
            validate_str_no_null(b"hello", "field")


class TestValidateStrNotEmpty:
    def test_normal_string_passes(self) -> None:
        validate_str_not_empty("hello", "field")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="field must not be empty"):
            validate_str_not_empty("", "field")

    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ValueError, match="field contains null bytes"):
            validate_str_not_empty("hello\x00world", "field")

    def test_non_string_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got int"):
            validate_str_not_empty(42, "field")

    def test_none_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a str, got NoneType"):
            validate_str_not_empty(None, "field")

    def test_whitespace_only_passes(self) -> None:
        validate_str_not_empty("  ", "field")


class TestValidateMapping:
    def test_dict_accepted(self) -> None:
        validate_mapping({"a": 1}, "field")

    def test_empty_dict_accepted(self) -> None:
        validate_mapping({}, "field")

    def test_mapping_proxy_accepted(self) -> None:
        validate_mapping(MappingProxyType({"a": 1}), "field")

    def test_list_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a Mapping, got list"):
            validate_mapping([1, 2], "field")

    def test_string_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a Mapping, got str"):
            validate_mapping("not a dict", "field")

    def test_none_rejected(self) -> None:
        with pytest.raises(TypeError, match="field must be a Mapping, got NoneType"):
            validate_mapping(None, "field")


class TestValidateJsonData:
    """validate_json_data: strict JSON compatibility with no lossy fallback."""

    def test_string_accepted(self) -> None:
        validate_json_data("hello", "d")

    def test_int_accepted(self) -> None:
        validate_json_data(42, "d")

    def test_bool_accepted(self) -> None:
        validate_json_data(True, "d")

    def test_false_accepted(self) -> None:
        validate_json_data(False, "d")

    def test_finite_float_accepted(self) -> None:
        validate_json_data(3.14, "d")

    def test_infinite_float_rejected(self) -> None:
        with pytest.raises(ValueError, match="d contains a non-finite float"):
            validate_json_data(float("inf"), "d")

    def test_negative_infinite_float_rejected(self) -> None:
        with pytest.raises(ValueError, match="d contains a non-finite float"):
            validate_json_data(float("-inf"), "d")

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError, match="d contains a non-finite float"):
            validate_json_data(float("nan"), "d")

    def test_none_accepted(self) -> None:
        validate_json_data(None, "d")

    def test_null_byte_in_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data("hello\x00", "data")

    def test_null_byte_in_dict_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data({"key": "val\x00ue"}, "data")

    def test_null_byte_in_dict_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="data key contains null bytes"):
            validate_json_data({"ke\x00y": "value"}, "data")

    def test_null_byte_in_nested_dict_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data({"outer": {"inner": "val\x00"}}, "data")

    def test_null_byte_in_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data(["ok", "bad\x00"], "data")

    def test_null_byte_in_nested_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data({"key": ["ok", "bad\x00"]}, "data")

    def test_non_string_keys_rejected(self) -> None:
        with pytest.raises(TypeError, match="d keys must be str, got int"):
            validate_json_data({1: "int_key", "ok": "str_key"}, "d")

    def test_non_serializable_value_rejected(self) -> None:
        class Custom:
            pass

        with pytest.raises(TypeError, match="d contains unsupported type Custom"):
            validate_json_data({"valid": "ok", "invalid": Custom()}, "d")

    def test_tuple_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="contains a tuple"):
            validate_json_data((1, 2, 3), "data")

    def test_tuple_in_dict_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="contains a tuple"):
            validate_json_data({"key": (1, 2)}, "data")

    def test_exceeds_max_depth_rejected(self) -> None:
        with pytest.raises(ValueError, match="d exceeds max depth of 1"):
            validate_json_data({"a": {"nested": "deep"}}, "d", max_depth=1)

    def test_within_max_depth_accepted(self) -> None:
        validate_json_data({"a": {"nested": "deep"}}, "d", max_depth=2)

    def test_max_depth_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="d exceeds max depth of 0"):
            validate_json_data({"a": 1}, "d", max_depth=0)

    def test_mapping_proxy_traversed(self) -> None:
        proxy = MappingProxyType({"key": "val\x00ue"})
        with pytest.raises(ValueError, match="data contains null bytes"):
            validate_json_data(proxy, "data")

    def test_mapping_proxy_accepted(self) -> None:
        proxy = MappingProxyType({"b": 2, "a": 1, "c": None})
        validate_json_data(proxy, "d")


class TestNormalizeJsonData:
    """normalize_json_data: deterministic normalization after validation."""

    def test_preserves_string(self) -> None:
        assert normalize_json_data("hello", "d") == "hello"

    def test_preserves_int(self) -> None:
        assert normalize_json_data(42, "d") == 42

    def test_preserves_bool(self) -> None:
        assert normalize_json_data(True, "d") is True

    def test_preserves_false(self) -> None:
        assert normalize_json_data(False, "d") is False

    def test_preserves_finite_float(self) -> None:
        assert normalize_json_data(3.14, "d") == 3.14

    def test_none_preserved(self) -> None:
        assert normalize_json_data(None, "d") is None

    def test_sorts_keys(self) -> None:
        result = normalize_json_data({"b": 2, "a": 1}, "d")
        assert list(result.keys()) == ["a", "b"]

    def test_preserves_none_values(self) -> None:
        result = normalize_json_data({"a": 1, "b": None}, "d")
        assert result == {"a": 1, "b": None}

    def test_preserves_empty_dict(self) -> None:
        result = normalize_json_data({"a": 1, "b": {}}, "d")
        assert result == {"a": 1, "b": {}}

    def test_preserves_empty_list(self) -> None:
        result = normalize_json_data({"a": 1, "b": []}, "d")
        assert result == {"a": 1, "b": []}

    def test_empty_dict_returns_empty(self) -> None:
        assert normalize_json_data({}, "d") == {}

    def test_list_preserved(self) -> None:
        result = normalize_json_data([1, None, "hello", {}], "d")
        assert result == [1, None, "hello", {}]

    def test_empty_list_returns_empty(self) -> None:
        assert normalize_json_data([], "d") == []

    def test_deeply_nested(self) -> None:
        result = normalize_json_data({"l1": {"l2": {"l3": "value"}}}, "d")
        assert result == {"l1": {"l2": {"l3": "value"}}}

    def test_list_inside_dict(self) -> None:
        result = normalize_json_data({"items": [1, 2, 3]}, "d")
        assert result == {"items": [1, 2, 3]}

    def test_dict_inside_list(self) -> None:
        result = normalize_json_data([{"a": 1}, {"b": 2}], "d")
        assert result == [{"a": 1}, {"b": 2}]

    def test_within_max_depth_preserved(self) -> None:
        result = normalize_json_data({"a": {"nested": "deep"}}, "d", max_depth=2)
        assert result == {"a": {"nested": "deep"}}

    def test_mapping_proxy_normalized(self) -> None:
        proxy = MappingProxyType({"b": 2, "a": 1, "c": None})
        result = normalize_json_data(proxy, "d")
        assert result == {"a": 1, "b": 2, "c": None}
        assert list(result.keys()) == ["a", "b", "c"]


class TestDeepFreeze:
    def test_dict_becomes_mapping_proxy(self) -> None:
        result = deep_freeze({"a": 1})
        assert isinstance(result, MappingProxyType)
        assert result["a"] == 1

    def test_nested_dict_frozen(self) -> None:
        result = deep_freeze({"outer": {"inner": 42}})
        assert isinstance(result, MappingProxyType)
        assert isinstance(result["outer"], MappingProxyType)
        assert result["outer"]["inner"] == 42

    def test_frozen_dict_rejects_mutation(self) -> None:
        result = deep_freeze({"a": 1})
        with pytest.raises(TypeError):
            result["b"] = 2  # type: ignore[index]

    def test_nested_frozen_dict_rejects_mutation(self) -> None:
        result = deep_freeze({"outer": {"inner": 1}})
        with pytest.raises(TypeError):
            result["outer"]["new"] = 2  # type: ignore[index]

    def test_list_contents_frozen(self) -> None:
        result = deep_freeze({"items": [{"a": 1}]})
        assert isinstance(result["items"], tuple)
        assert isinstance(result["items"][0], MappingProxyType)

    def test_list_rejects_mutation(self) -> None:
        result = deep_freeze({"items": [1, 2, 3]})
        with pytest.raises(TypeError):
            result["items"][0] = 99  # type: ignore[index]

    def test_list_becomes_tuple(self) -> None:
        result = deep_freeze([1, 2, 3])
        assert isinstance(result, tuple)
        assert result == (1, 2, 3)

    def test_primitives_unchanged(self) -> None:
        assert deep_freeze(42) == 42
        assert deep_freeze("hello") == "hello"
        assert deep_freeze(None) is None
        assert deep_freeze(True) is True

    def test_empty_dict(self) -> None:
        result = deep_freeze({})
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_empty_list(self) -> None:
        result = deep_freeze([])
        assert isinstance(result, tuple)
        assert result == ()
