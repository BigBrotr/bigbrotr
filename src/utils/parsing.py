"""Shared parsing utilities for NIP model validation.

This module provides type-safe parsing of data against TypedDict schemas,
used primarily for validating NIP-11 and NIP-66 relay metadata responses.
It uses Python's typing introspection (get_type_hints, get_origin, get_args)
to automatically validate field types.

Key Features:
    - Automatic type validation against TypedDict schemas
    - Graceful handling of invalid/missing data (normalized to None)
    - List element filtering (removes invalid elements)
    - Empty string/collection normalization to None

Limitations:
    - Nested TypedDict fields are skipped (caller must handle separately)
    - Complex generic types beyond list[T] are not supported

Example:
    >>> from typing import TypedDict
    >>> class RelayInfo(TypedDict, total=False):
    ...     name: str
    ...     supported_nips: list[int]
    >>> data = {"name": "My Relay", "supported_nips": [1, "invalid", 11]}
    >>> result = parse_typed_dict(data, RelayInfo)
    >>> # result = {"name": "My Relay", "supported_nips": [1, 11]}
"""

from __future__ import annotations

from typing import Any, get_args, get_origin, get_type_hints, is_typeddict


def parse_typed_dict(data: dict[str, Any], schema: type) -> dict[str, Any]:
    """Parse and validate data against a TypedDict schema.

    Validates each field in the input data against the expected types defined
    in the TypedDict schema. Invalid values are normalized to None rather than
    raising exceptions, making this suitable for parsing untrusted external data.

    Processing Rules:
        - All keys defined in schema are included in result
        - Missing keys are set to None
        - Wrong types are normalized to None
        - Empty strings (after strip) become None
        - Empty collections (list, dict, set, tuple) become None
        - List elements are filtered: invalid/empty elements removed
        - Nested TypedDict fields are set to None (caller handles)

    Args:
        data: Raw dictionary to parse, typically from JSON response.
            Unknown keys not in schema are ignored.
        schema: A TypedDict class defining the expected structure.
            Uses get_type_hints() to extract field types.

    Returns:
        dict[str, Any]: Dictionary with all schema keys present.
            Values are either the validated data or None for invalid/missing.

    Note:
        TypedDict fields and list[TypedDict] types are intentionally skipped
        and set to None. The caller should handle these with custom parsing
        logic appropriate to the specific nested structure.

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
                if isinstance(v, list | dict | set | tuple) and not v:
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
