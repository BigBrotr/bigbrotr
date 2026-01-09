"""
Shared parsing utilities for NIP models.

Provides type-safe parsing of data against TypedDict schemas using
get_type_hints() for automatic type validation.
"""

from __future__ import annotations

from typing import Any, get_args, get_origin, get_type_hints, is_typeddict


def parse_typed_dict(data: dict[str, Any], schema: type) -> dict[str, Any]:
    """Parse and validate data against a TypedDict schema.

    All keys defined in the schema are included in the result.
    Invalid types, empty strings, and empty iterables are normalized to None.
    List elements with invalid types or empty values are filtered out.

    Note: TypedDict fields and complex nested types (list[TypedDict]) are
    skipped - they should be handled by the caller with custom parsing.

    Args:
        data: Raw data dict to parse
        schema: TypedDict class defining expected structure

    Returns:
        Dict with all schema keys, invalid/missing values as None

    Example:
        >>> class MyData(TypedDict, total=False):
        ...     name: str
        ...     count: int
        ...     tags: list[str]
        >>> parse_typed_dict({"name": "Test", "count": "invalid"}, MyData)
        {'name': 'Test', 'count': None, 'tags': None}
    """
    result: dict[str, Any] = {}

    for key, expected_type in get_type_hints(schema).items():
        val = data.get(key)

        # Missing values -> None
        if val is None:
            result[key] = None
            continue

        # Handle list types: filter elements by inner type
        if get_origin(expected_type) is list:
            if not isinstance(val, list):
                result[key] = None
                continue

            inner_types = get_args(expected_type)
            if not inner_types:
                # list without type arg - keep as is if non-empty
                result[key] = val if val else None
                continue

            inner_type = inner_types[0]

            # Skip if inner type is TypedDict (needs custom parsing)
            if is_typeddict(inner_type):
                result[key] = None  # Caller should handle this
                continue

            # Filter: keep only valid elements
            filtered = []
            for v in val:
                if v is None:
                    continue
                # Check inner type
                if not isinstance(v, inner_type):
                    continue
                # Skip empty strings
                if isinstance(v, str) and not v.strip():
                    continue
                # Skip empty iterables (list, dict, set, tuple)
                if isinstance(v, (list, dict, set, tuple)) and not v:
                    continue
                filtered.append(v)

            result[key] = filtered if filtered else None
            continue

        # Skip TypedDict fields - they need custom parsing
        if is_typeddict(expected_type):
            result[key] = None  # Caller should handle this
            continue

        # Wrong type -> None
        if not isinstance(val, expected_type):
            result[key] = None
            continue

        # Empty string -> None
        if isinstance(val, str) and not val.strip():
            result[key] = None
            continue

        result[key] = val

    return result
