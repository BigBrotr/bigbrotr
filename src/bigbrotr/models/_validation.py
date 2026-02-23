"""Shared validation helpers for frozen dataclass models.

Private module — not part of the public API. Used exclusively by
``__post_init__`` methods in sibling model modules to enforce runtime
type constraints, null-byte safety, and deep immutability.
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


def sanitize_data(
    obj: Any,
    name: str,
    *,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    _depth: int = 0,
) -> Any:
    """Recursively normalize an object for deterministic JSON serialization.

    * Removes ``None`` values and empty containers (``{}``, ``[]``).
    * Sorts dictionary keys for consistent ordering.
    * Rejects strings and dict keys containing null bytes (PostgreSQL incompatible).
    * Non-serializable types are replaced with ``None``.

    Args:
        obj: The value to sanitize.
        name: Field name for error messages.
        max_depth: Maximum recursion depth (defaults to 50).
        _depth: Current recursion depth (internal use).

    Returns:
        The sanitized object, or ``None`` for unserializable values.

    Raises:
        ValueError: If any string value or dict key contains null bytes.
    """
    if _depth > max_depth:
        return None

    if (
        obj is None
        or isinstance(obj, bool | int)
        or (isinstance(obj, float) and math.isfinite(obj))
    ):
        return obj

    if isinstance(obj, str):
        if "\x00" in obj:
            raise ValueError(f"{name} contains null bytes")
        return obj

    if isinstance(obj, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(k for k in obj if isinstance(k, str)):
            if "\x00" in key:
                raise ValueError(f"{name} key contains null bytes")
            v = sanitize_data(obj[key], name, max_depth=max_depth, _depth=_depth + 1)
            if _is_empty(v):
                continue
            result[key] = v
        return result

    if isinstance(obj, list):
        result_list: list[Any] = []
        for item in obj:
            v = sanitize_data(item, name, max_depth=max_depth, _depth=_depth + 1)
            if _is_empty(v):
                continue
            result_list.append(v)
        return result_list

    if isinstance(obj, tuple):
        raise TypeError(f"{name} contains a tuple; use list for JSON-serializable sequences")

    return None


def _is_empty(v: Any) -> bool:
    """Return True if the value is None or an empty container."""
    if v is None:
        return True
    return bool(isinstance(v, (dict, list)) and not v)


def deep_freeze(obj: Any) -> Any:
    """Recursively wrap dicts with ``MappingProxyType`` to prevent mutation."""
    if isinstance(obj, dict):
        return MappingProxyType({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [deep_freeze(item) for item in obj]
    return obj
