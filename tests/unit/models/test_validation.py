"""Tests for bigbrotr.models._validation shared helpers."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from bigbrotr.models._validation import (
    deep_freeze,
    sanitize_data,
    validate_instance,
    validate_mapping,
    validate_str_no_null,
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


class TestSanitizeData:
    """sanitize_data: recursive normalization with null byte and type safety."""

    # --- Primitives ---

    def test_preserves_string(self) -> None:
        assert sanitize_data("hello", "d") == "hello"

    def test_preserves_int(self) -> None:
        assert sanitize_data(42, "d") == 42

    def test_preserves_bool(self) -> None:
        assert sanitize_data(True, "d") is True

    def test_preserves_finite_float(self) -> None:
        assert sanitize_data(3.14, "d") == 3.14

    def test_infinite_float_becomes_none(self) -> None:
        assert sanitize_data(float("inf"), "d") is None

    def test_nan_becomes_none(self) -> None:
        assert sanitize_data(float("nan"), "d") is None

    def test_none_preserved(self) -> None:
        assert sanitize_data(None, "d") is None

    # --- Null bytes ---

    def test_null_byte_in_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data("hello\x00", "data")

    def test_null_byte_in_dict_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data({"key": "val\x00ue"}, "data")

    def test_null_byte_in_dict_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="data key contains null bytes"):
            sanitize_data({"ke\x00y": "value"}, "data")

    def test_null_byte_in_nested_dict_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data({"outer": {"inner": "val\x00"}}, "data")

    def test_null_byte_in_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data(["ok", "bad\x00"], "data")

    def test_null_byte_in_nested_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data({"key": ["ok", "bad\x00"]}, "data")

    # --- Dict normalization ---

    def test_sorts_keys(self) -> None:
        result = sanitize_data({"b": 2, "a": 1}, "d")
        assert list(result.keys()) == ["a", "b"]

    def test_removes_none_values(self) -> None:
        result = sanitize_data({"a": 1, "b": None}, "d")
        assert result == {"a": 1}

    def test_removes_empty_dict(self) -> None:
        result = sanitize_data({"a": 1, "b": {}}, "d")
        assert result == {"a": 1}

    def test_removes_empty_list(self) -> None:
        result = sanitize_data({"a": 1, "b": []}, "d")
        assert result == {"a": 1}

    def test_non_string_keys_skipped(self) -> None:
        result = sanitize_data({1: "int_key", "ok": "str_key"}, "d")
        assert result == {"ok": "str_key"}

    def test_non_serializable_filtered_out(self) -> None:
        class Custom:
            pass

        result = sanitize_data({"valid": "ok", "invalid": Custom()}, "d")
        assert result == {"valid": "ok"}

    def test_empty_dict_returns_empty(self) -> None:
        assert sanitize_data({}, "d") == {}

    # --- List normalization ---

    def test_list_cleaned(self) -> None:
        result = sanitize_data([1, None, "hello", {}], "d")
        assert result == [1, "hello"]

    def test_empty_list_returns_empty(self) -> None:
        assert sanitize_data([], "d") == []

    # --- Nested structures ---

    def test_deeply_nested(self) -> None:
        result = sanitize_data({"l1": {"l2": {"l3": "value"}}}, "d")
        assert result == {"l1": {"l2": {"l3": "value"}}}

    def test_list_inside_dict(self) -> None:
        result = sanitize_data({"items": [1, 2, 3]}, "d")
        assert result == {"items": [1, 2, 3]}

    def test_dict_inside_list(self) -> None:
        result = sanitize_data([{"a": 1}, {"b": 2}], "d")
        assert result == [{"a": 1}, {"b": 2}]

    # --- Max depth ---

    def test_exceeds_max_depth_truncates(self) -> None:
        # depth 0: outer dict, depth 1: inner dict, depth 2 > max_depth → values become None
        # empty containers are pruned, so nested dicts collapse to {}
        result = sanitize_data({"a": {"nested": "deep"}}, "d", max_depth=1)
        assert result == {}

    def test_within_max_depth_preserved(self) -> None:
        result = sanitize_data({"a": {"nested": "deep"}}, "d", max_depth=2)
        assert result == {"a": {"nested": "deep"}}

    # --- MappingProxyType (roundtrip) ---

    def test_mapping_proxy_traversed(self) -> None:
        proxy = MappingProxyType({"key": "val\x00ue"})
        with pytest.raises(ValueError, match="data contains null bytes"):
            sanitize_data(proxy, "data")

    def test_mapping_proxy_sanitized(self) -> None:
        proxy = MappingProxyType({"b": 2, "a": 1, "c": None})
        result = sanitize_data(proxy, "d")
        assert result == {"a": 1, "b": 2}
        assert list(result.keys()) == ["a", "b"]


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
