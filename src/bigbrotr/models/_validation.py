"""Shared validation and normalization helpers for frozen dataclass models.

Private module — not part of the public API. Used exclusively by
``__post_init__`` methods in sibling model modules to enforce runtime
type constraints, strict JSON compatibility, null-byte safety, and deep
immutability.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


_DEFAULT_MAX_DEPTH: int = 50


def validate_instance(value: Any, expected: type, name: str) -> None:
    """Raise ``TypeError`` if *value* is not an instance of *expected*."""
    if not isinstance(value, expected):
        article = "an" if expected.__name__[0] in "AEIOUaeiou" else "a"
        raise TypeError(f"{name} must be {article} {expected.__name__}, got {type(value).__name__}")


def validate_timestamp(value: Any, name: str) -> None:
    """Raise if *value* is not a non-negative ``int`` (``bool`` excluded)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def validate_str_no_null(value: Any, name: str) -> None:
    """Raise if *value* is not a ``str`` or contains null bytes."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if "\x00" in value:
        raise ValueError(f"{name} contains null bytes")


def validate_str_not_empty(value: Any, name: str) -> None:
    """Raise if *value* is not a non-empty ``str`` without null bytes."""
    validate_str_no_null(value, name)
    if not value:
        raise ValueError(f"{name} must not be empty")


def validate_mapping(value: Any, name: str) -> None:
    """Raise ``TypeError`` if *value* is not a ``Mapping``."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a Mapping, got {type(value).__name__}")


def validate_json_data(
    obj: Any,
    name: str,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    _depth: int = 0,
) -> None:
    """Validate that a value is strictly JSON-compatible.

    Args:
        obj: The value to validate.
        name: Field name for error messages.
        max_depth: Maximum recursion depth (defaults to 50).
        _depth: Current recursion depth (internal use).

    Raises:
        TypeError: If the value contains unsupported JSON types.
        ValueError: If the value contains null bytes or non-finite floats.
    """
    if _depth > max_depth:
        raise ValueError(f"{name} exceeds max depth of {max_depth}")

    if (
        obj is None
        or isinstance(obj, bool | int)
        or (isinstance(obj, float) and math.isfinite(obj))
    ):
        return

    if isinstance(obj, float):
        raise ValueError(f"{name} contains a non-finite float")

    if isinstance(obj, str):
        if "\x00" in obj:
            raise ValueError(f"{name} contains null bytes")
        return

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} keys must be str, got {type(key).__name__}")
            if "\x00" in key:
                raise ValueError(f"{name} key contains null bytes")
            validate_json_data(value, name, max_depth=max_depth, _depth=_depth + 1)
        return

    if isinstance(obj, list):
        for item in obj:
            validate_json_data(item, name, max_depth=max_depth, _depth=_depth + 1)
        return

    if isinstance(obj, tuple):
        raise TypeError(f"{name} contains a tuple; use list for JSON-serializable sequences")

    raise TypeError(f"{name} contains unsupported type {type(obj).__name__}")


def normalize_json_data(
    obj: Any,
    name: str,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> Any:
    """Normalize a validated JSON-compatible value for deterministic serialization.

    The value is validated first, then normalized without changing its
    semantic content:

    * dictionary keys are sorted for consistent ordering
    * list order is preserved
    * ``None`` values and empty containers are preserved
    """
    validate_json_data(obj, name, max_depth=max_depth)
    return _normalize_json_data(obj, max_depth=max_depth)


def _normalize_json_data(
    obj: Any,
    *,
    max_depth: int,
    _depth: int = 0,
) -> Any:
    """Normalize a JSON-compatible value after validation has succeeded."""
    if _depth > max_depth:
        raise ValueError(f"value exceeds max depth of {max_depth}")

    if (
        obj is None
        or isinstance(obj, bool | int)
        or (isinstance(obj, float) and math.isfinite(obj))
        or isinstance(obj, str)
    ):
        return obj

    if isinstance(obj, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(obj):
            result[key] = _normalize_json_data(obj[key], max_depth=max_depth, _depth=_depth + 1)
        return result

    if isinstance(obj, list):
        return [_normalize_json_data(item, max_depth=max_depth, _depth=_depth + 1) for item in obj]

    raise TypeError(f"value contains unsupported type {type(obj).__name__}")


def deep_freeze(obj: Any) -> Any:
    """Recursively wrap dicts with ``MappingProxyType`` to prevent mutation."""
    if isinstance(obj, dict):
        return MappingProxyType({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(deep_freeze(item) for item in obj)
    return obj
